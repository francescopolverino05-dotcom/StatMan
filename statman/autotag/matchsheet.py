"""Match sheet (distinta / referee report) facts that override auto-tags.

Flow: upload a PDF or image -> pages rendered to PNG -> vision model (OpenRouter,
same TAGGER_API_URL / TAGGER_API_KEY as the tagger; model MATCHSHEET_MODEL,
default google/gemini-2.5-flash) reads them into strict JSON -> the draft is
shown editable -> only a *confirmed* sheet is applied:

* goals / cards: tagged ones that match the sheet (same team, close minute) are
  corrected (scorer, minute); tagged ones not on the sheet are rejected
  (phantoms); sheet ones with no tag are added, flagged "from match sheet".
* clock anchors: tagged goals matched to sheet goals give the clip clock
  offset per half; AI events are shifted by the median offset.
* lineups + subs -> lineup doc (on/off minutes) so per-player minutes work,
  and AI events whose shirt is not on the pitch at that minute lose the
  attribution and go back to review.

Facts schema (minutes are ints, or "45+2" strings)::

    {"home_team": str, "away_team": str,
     "lineups": {"home": [{"number", "name", "position", "starter"}], "away": [...]},
     "subs":  [{"minute", "team", "off", "on"}],          # off/on = shirt number or name
     "goals": [{"minute", "team", "scorer", "assist", "own_goal"}],
     "cards": [{"minute", "team", "player", "colour"}]}
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import statistics
import time
from typing import Any

from statman.autotag import store
from statman.autotag.repo import EventRepo, get_repo

TEAMS = ("home", "away")
SHEET_TAG = "from match sheet"
DEFAULT_MODEL = "google/gemini-2.5-flash"
GOAL_WINDOW_S = 300.0      # a tagged goal within 5 min of a sheet goal (after offset) is the same goal
CARD_WINDOW_S = 300.0
ANCHOR_WINDOW_S = 900.0    # raw (pre-offset) search window for clock anchors
MAX_PAGES = 6


# ---------------------------------------------------------------------------
# Facts validation
# ---------------------------------------------------------------------------


def parse_minute(value: Any) -> float | None:
    """18 -> 18.0, "45+2" -> 47.0, "70'" -> 70.0. None if unreadable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if 0 <= value <= 150 else None
    m = re.fullmatch(r"\s*(\d{1,3})\s*(?:\+\s*(\d{1,2}))?\s*'?\s*", str(value))
    if not m:
        return None
    total = float(int(m.group(1)) + int(m.group(2) or 0))
    return total if total <= 150 else None


def minute_to_seconds(minute: float) -> float:
    """Sheet minute N means the event happened during minute N (N-1:00 .. N-1:59)."""
    return max(0.0, (minute - 1.0) * 60.0 + 30.0)


def _team(value: Any, facts: dict[str, Any]) -> str | None:
    v = str(value or "").strip().lower()
    if v in TEAMS:
        return v
    for t in TEAMS:
        name = str(facts.get(f"{t}_team") or "").strip().lower()
        if name and (v == name or (v and (v in name or name in v))):
            return t
    return None


def _shirt(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = int(str(value).strip().lstrip("#"))
    except ValueError:
        return None
    return n if 0 <= n <= 99 else None


def _str(value: Any) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def validate_facts(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Coerce model or form output into the strict facts schema. Returns (facts, issues)."""
    issues: list[str] = []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("match sheet facts must be a JSON object")
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    facts: dict[str, Any] = {
        "home_team": _str(raw.get("home_team") or teams.get("home")),
        "away_team": _str(raw.get("away_team") or teams.get("away")),
        "lineups": {"home": [], "away": []}, "subs": [], "goals": [], "cards": [],
    }
    lineups = raw.get("lineups") if isinstance(raw.get("lineups"), dict) else {}
    for t in TEAMS:
        seen: set[int] = set()
        for i, p in enumerate(lineups.get(t) or []):
            if not isinstance(p, dict):
                continue
            num = _shirt(p.get("number", p.get("shirt")))
            if num is None:
                issues.append(f"{t} lineup row {i + 1}: missing shirt number")
                continue
            if num in seen:
                issues.append(f"{t} lineup: shirt {num} listed twice")
                continue
            seen.add(num)
            starter = p.get("starter")
            facts["lineups"][t].append({
                "number": num, "name": _str(p.get("name")), "position": _str(p.get("position")),
                "starter": bool(starter) if starter is not None else len(seen) <= 11,
            })
    for kind, fields in (("subs", ("off", "on")), ("goals", ("scorer", "assist")), ("cards", ("player",))):
        for i, row in enumerate(raw.get(kind) or []):
            if not isinstance(row, dict):
                continue
            minute = parse_minute(row.get("minute"))
            team = _team(row.get("team"), facts)
            if minute is None:
                issues.append(f"{kind} row {i + 1}: unreadable minute {row.get('minute')!r}")
                continue
            out: dict[str, Any] = {"minute": minute, "team": team}
            for f in fields:
                v = row.get(f)
                out[f] = _shirt(v) if _shirt(v) is not None else _str(v)
            if kind == "goals":
                out["own_goal"] = bool(row.get("own_goal"))
            if kind == "cards":
                colour = str(row.get("colour") or row.get("color") or "").strip().lower()
                colour = {"giallo": "yellow", "rosso": "red", "y": "yellow", "r": "red"}.get(colour, colour)
                if colour not in {"yellow", "red"}:
                    issues.append(f"cards row {i + 1}: colour must be yellow or red")
                    continue
                out["colour"] = colour
            if team is None:
                team = _infer_team(out, fields, facts)
                out["team"] = team
            if team is None:
                issues.append(f"{kind} row {i + 1}: team unknown")
                continue
            facts[kind].append(out)
        facts[kind].sort(key=lambda r: r["minute"])
    return facts, issues


def _infer_team(row: dict[str, Any], fields: tuple[str, ...], facts: dict[str, Any]) -> str | None:
    for t in TEAMS:
        for f in fields:
            if row.get(f) is not None and resolve_player(facts, t, row[f]) is not None:
                return t
    return None


def resolve_player(facts: dict[str, Any], team: str, ref: Any) -> dict[str, Any] | None:
    """Find a lineup entry by shirt number or (sur)name."""
    players = (facts.get("lineups") or {}).get(team) or []
    num = _shirt(ref)
    if num is not None:
        return next((p for p in players if p["number"] == num), None)
    name = str(ref or "").strip().lower()
    if not name:
        return None
    for p in players:
        if (p.get("name") or "").strip().lower() == name:
            return p
    hits = [p for p in players if p.get("name") and (name in p["name"].lower() or p["name"].lower() in name)]
    return hits[0] if len(hits) == 1 else None


# ---------------------------------------------------------------------------
# Who is on the pitch
# ---------------------------------------------------------------------------


def lineup_doc(facts: dict[str, Any], match_minutes: float = 90.0) -> dict[str, Any]:
    """Lineup doc for stats (team, shirt, name, position, starter, on_minute, off_minute)."""
    players: list[dict[str, Any]] = []
    for t in TEAMS:
        for p in facts["lineups"][t]:
            players.append({"team": t, "shirt": p["number"], "name": p.get("name"), "position": p.get("position"),
                            "starter": p["starter"], "on_minute": None, "off_minute": None})
    by_key = {(p["team"], p["shirt"]): p for p in players}
    for s in facts["subs"]:
        off = resolve_player(facts, s["team"], s.get("off"))
        on = resolve_player(facts, s["team"], s.get("on"))
        if off:
            by_key[(s["team"], off["number"])]["off_minute"] = s["minute"]
        if on:
            by_key[(s["team"], on["number"])]["on_minute"] = s["minute"]
    for c in facts["cards"]:
        if c["colour"] == "red":
            p = resolve_player(facts, c["team"], c.get("player"))
            if p and by_key[(c["team"], p["number"])]["off_minute"] is None:
                by_key[(c["team"], p["number"])]["off_minute"] = c["minute"]
    return {"match_minutes": match_minutes, "players": players, "source": "match_sheet"}


def on_pitch(lineup: dict[str, Any], team: str, shirt: int, minute: float, slack: float = 1.0) -> bool | None:
    """True/False if the shirt is (not) on the pitch at ``minute``; None if the team has no lineup."""
    rows = [p for p in lineup.get("players") or [] if p.get("team") == team]
    if not rows:
        return None
    for p in rows:
        if int(p["shirt"]) != shirt:
            continue
        start = p.get("on_minute")
        if start is None:
            if not p.get("starter"):
                return False
            start = 0.0
        end = p.get("off_minute")
        return float(start) - slack <= minute <= (float(end) + slack if end is not None else 1e9)
    return False


# ---------------------------------------------------------------------------
# Applying confirmed facts
# ---------------------------------------------------------------------------


def _is_goal(ev: dict[str, Any]) -> bool:
    return ev["type"] == "goal"


def _live(ev: dict[str, Any]) -> bool:
    return ev.get("review_status") != "rejected"


def _from_sheet(ev: dict[str, Any]) -> bool:
    return SHEET_TAG in (ev.get("review_reason") or []) or (ev.get("detail") or "").startswith(SHEET_TAG)


def _half(minute: float) -> int:
    return 1 if minute <= 45.5 else 2


def clock_anchors(events: list[dict[str, Any]], facts: dict[str, Any]) -> dict[str, Any]:
    """Pair sheet goals (and tagged sub/card events if any) with tagged ones; offset per half = sheet - tagged."""
    pairs: list[dict[str, Any]] = []
    used: set[int] = set()
    tagged = [e for e in events if _live(e) and e.get("source") == "ai"]
    for kind, etype, rows in (("goal", "goal", facts["goals"]), ("card", "card", facts["cards"])):
        for g in rows:
            want = minute_to_seconds(g["minute"])
            cands = [e for e in tagged if e["type"] == etype and e.get("team") == g["team"] and e["id"] not in used
                     and abs(e["t_match_seconds"] - want) <= ANCHOR_WINDOW_S]
            if kind == "card":
                cands = [e for e in cands if (e.get("attributes") or {}).get("color") == g["colour"]]
            if not cands:
                continue
            best = min(cands, key=lambda e: abs(e["t_match_seconds"] - want))
            used.add(best["id"])
            pairs.append({"kind": kind, "minute": g["minute"], "event_id": best["id"],
                          "tagged_seconds": best["t_match_seconds"], "offset_seconds": want - best["t_match_seconds"]})
    offsets: dict[int, float] = {}
    for half in (1, 2):
        vals = [p["offset_seconds"] for p in pairs if _half(p["minute"]) == half]
        # goals pin the clock better than cards (cards are often shown late)
        goal_vals = [p["offset_seconds"] for p in pairs if _half(p["minute"]) == half and p["kind"] == "goal"]
        use = goal_vals or vals
        if use:
            offsets[half] = round(statistics.median(use), 1)
    if len(offsets) == 1:
        offsets[2 if 1 in offsets else 1] = next(iter(offsets.values()))
    return {"pairs": pairs, "offsets": {str(k): v for k, v in sorted(offsets.items())}}


def _shift(t: float, offsets: dict[str, float]) -> float:
    if not offsets:
        return t
    half = "1" if t <= 45.5 * 60 else "2"
    off = offsets.get(half, offsets.get("1", 0.0))
    return max(0.0, round(t + off, 2))


def apply_facts(match_id: str, facts: dict[str, Any], *, repo: EventRepo | None = None,
                reviewer: str | None = "match sheet", min_offset_s: float = 5.0) -> dict[str, Any]:
    """Apply confirmed facts to the tagged events. Idempotent: re-applying the same sheet changes nothing new."""
    repo = repo or get_repo()
    facts, issues = validate_facts(facts)
    report: dict[str, Any] = {"issues": issues, "shifted": 0, "goals": {"corrected": [], "rejected": [], "added": []},
                              "cards": {"corrected": [], "rejected": [], "added": []},
                              "attribution_cleared": [], "names_filled": 0}

    def log(ev_id: int, action: str, before: dict[str, Any], after: dict[str, Any], note: str) -> None:
        repo.add_correction(match_id, {"event_id": ev_id, "action": action, "reviewer": reviewer, "note": note,
                                       "before": before, "after": after})

    def update(ev: dict[str, Any], fields: dict[str, Any], note: str, action: str = "edit") -> dict[str, Any]:
        before = {k: ev.get(k) for k in fields}
        new = repo.update_event(match_id, ev["id"], fields)
        log(ev["id"], action, before, {k: new.get(k) for k in fields}, note)
        return new

    # 1) clock offset from anchors (only AI events move; human/sheet events are already on the real clock)
    events = repo.list_events(match_id)
    anchors = clock_anchors(events, facts)
    report["clock"] = anchors
    offsets = {k: v for k, v in anchors["offsets"].items() if abs(v) >= min_offset_s}
    if offsets:
        for ev in events:
            if ev.get("source") == "ai" and not _from_sheet(ev):
                t = _shift(ev["t_match_seconds"], offsets)
                if t != ev["t_match_seconds"]:
                    repo.update_event(match_id, ev["id"], {"t_match_seconds": t})
                    report["shifted"] += 1
        if report["shifted"]:
            repo.add_correction(match_id, {"event_id": 0, "action": "clock_offset", "reviewer": reviewer,
                                           "note": "clip clock re-anchored from match sheet goal times",
                                           "before": {}, "after": {"offsets": offsets, "events": report["shifted"]}})
    events = repo.list_events(match_id)

    # 2) goals and cards
    for kind, etype, rows, window in (("goals", "goal", facts["goals"], GOAL_WINDOW_S),
                                      ("cards", "card", facts["cards"], CARD_WINDOW_S)):
        used: set[int] = set()
        tagged = [e for e in events if e["type"] == etype and _live(e)]
        for row in rows:
            want = minute_to_seconds(row["minute"])
            ref = row.get("scorer") if kind == "goals" else row.get("player")
            # own goal: scorer is in the other team's lineup
            pteam = ("away" if row["team"] == "home" else "home") if row.get("own_goal") else row["team"]
            player = resolve_player(facts, pteam, ref)
            shirt = player["number"] if player else (_shirt(ref))
            name = player.get("name") if player else (ref if isinstance(ref, str) else None)
            attrs: dict[str, Any] = {}
            if kind == "goals":
                assist = resolve_player(facts, row["team"], row.get("assist")) if row.get("assist") is not None else None
                attrs = {"own_goal": bool(row.get("own_goal"))}
                if assist:
                    attrs.update({"assist_shirt": assist["number"], "assist_player": assist.get("name")})
                elif row.get("assist") is not None:
                    attrs["assist_player"] = str(row["assist"])
            else:
                attrs = {"color": row["colour"]}
            cands = [e for e in tagged if e["id"] not in used and e.get("team") == row["team"]
                     and abs(e["t_match_seconds"] - want) <= window
                     and (kind == "goals" or (e.get("attributes") or {}).get("color") == row["colour"])]
            note = f"{SHEET_TAG}: {etype} {row['minute']:g}'"
            if cands:
                ev = min(cands, key=lambda e: abs(e["t_match_seconds"] - want))
                used.add(ev["id"])
                fields = {"shirt": shirt if pteam == row["team"] else None, "player": name,
                          "attributes": {**(ev.get("attributes") or {}), **attrs},
                          "review_status": "corrected", "confidence": 1.0,
                          "review_reason": [SHEET_TAG], "issues": []}
                if ev.get("source") != "ai":
                    fields.pop("review_status")  # sheet/human events stay as they are
                if abs(ev["t_match_seconds"] - want) > 60:
                    fields["t_match_seconds"] = want
                changed = {k: v for k, v in fields.items() if ev.get(k) != v}
                if changed:
                    update(ev, changed, note)
                report[kind]["corrected"].append(ev["id"])
            else:
                new = {"type": etype, "team": row["team"], "shirt": shirt if pteam == row["team"] else None,
                       "player": name, "t_match_seconds": want, "video_ts_seconds": None, "period": _half(row["minute"]),
                       "x": None, "y": None, "outcome": "goal" if kind == "goals" else row["colour"],
                       "code": "GOAL" if kind == "goals" else "CARD", "detail": note, "attributes": attrs,
                       "confidence": 1.0, "review_status": "confirmed", "review_reason": [SHEET_TAG],
                       "issues": [], "clip_ids": [], "source": "human"}
                ev = repo.add_event(match_id, new)
                log(ev["id"], "add", {}, {k: ev.get(k) for k in ("type", "team", "shirt", "player", "t_match_seconds")}, note)
                used.add(ev["id"])
                report[kind]["added"].append(ev["id"])
        for ev in tagged:
            if ev["id"] in used:
                continue
            update(ev, {"review_status": "rejected", "review_reason": [f"not on match sheet ({SHEET_TAG})"]},
                   f"phantom {etype}: not on the match sheet", action="delete")
            report[kind]["rejected"].append(ev["id"])

    # 3) lineup + on-pitch constraint for shirt attribution
    events = repo.list_events(match_id)
    last = max((e["t_match_seconds"] for e in events), default=0.0) / 60.0
    lineup = lineup_doc(facts, match_minutes=float(max(90, int(last + 0.999), *(r["minute"] for r in facts["goals"] + facts["subs"] + facts["cards"]) )))
    if lineup["players"]:
        store.write_doc(match_id, "lineup", lineup)
        names = {(p["team"], int(p["shirt"])): p.get("name") for p in lineup["players"]}
        for ev in events:
            if not _live(ev) or ev.get("shirt") is None or ev.get("team") not in TEAMS or _from_sheet(ev):
                continue
            if ev.get("source") != "ai":
                continue
            minute = ev["t_match_seconds"] / 60.0
            ok = on_pitch(lineup, ev["team"], int(ev["shirt"]), minute)
            if ok is False:
                reason = list(ev.get("review_reason") or [])
                msg = f"shirt {ev['shirt']} not on the pitch at {minute:.0f}' per match sheet"
                fields = {"shirt": None, "player": None, "review_reason": reason + [msg]}
                if ev.get("review_status") == "auto":
                    fields["review_status"] = "pending"
                update(ev, fields, msg)
                report["attribution_cleared"].append(ev["id"])
            elif ok and names.get((ev["team"], int(ev["shirt"]))) and ev.get("player") != names[(ev["team"], int(ev["shirt"]))]:
                repo.update_event(match_id, ev["id"], {"player": names[(ev["team"], int(ev["shirt"]))]})
                report["names_filled"] += 1

    # 4) recompute stats and keep a snapshot
    from statman.autotag.stats import match_stats

    stats = match_stats(repo.list_events(match_id), store.read_doc(match_id, "lineup", None))
    store.write_doc(match_id, "stats", stats)
    report["score"] = {t: stats["teams"][t]["goals"] for t in TEAMS}
    report["applied_at"] = time.time()
    store.write_doc(match_id, "matchsheet_apply", report)
    return {"report": report, "stats": stats}


# ---------------------------------------------------------------------------
# Reading the sheet with the vision model
# ---------------------------------------------------------------------------


def render_pages(data: bytes, filename: str = "", *, scale: float = 2.0, max_pages: int = MAX_PAGES) -> list[bytes]:
    """PDF -> PNG bytes per page (pypdfium2). Images are re-encoded as PNG."""
    from PIL import Image

    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        out: list[bytes] = []
        try:
            for i in range(min(len(pdf), max_pages)):
                img = pdf[i].render(scale=scale).to_pil().convert("RGB")
                img = _limit(img)
                buf = io.BytesIO()
                img.save(buf, "PNG")
                out.append(buf.getvalue())
        finally:
            pdf.close()
        return out
    img = _limit(Image.open(io.BytesIO(data)).convert("RGB"))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return [buf.getvalue()]


def _limit(img, max_side: int = 2400):
    w, h = img.size
    if max(w, h) > max_side:
        f = max_side / max(w, h)
        img = img.resize((int(w * f), int(h * f)))
    return img


SHEET_PROMPT = """You read official football match sheets (Italian "distinta" / referee report), often scanned.
Return ONLY JSON with exactly these keys:
{"home_team": str, "away_team": str,
 "lineups": {"home": [{"number": int, "name": str, "position": str|null, "starter": bool}], "away": [...]},
 "subs": [{"minute": int|str, "team": "home"|"away", "off": int, "on": int}],
 "goals": [{"minute": int|str, "team": "home"|"away", "scorer": str, "assist": str|null, "own_goal": bool}],
 "cards": [{"minute": int|str, "team": "home"|"away", "player": str, "colour": "yellow"|"red"}]}
Rules: copy only what is written; never guess. team = the team that SCORED (for own goals too).
Players in "subs" are shirt numbers. Minutes like 45+2 as the string "45+2". Starters are the first 11 listed
(titolari); reserves (riserve / panchina) have starter false. Empty lists when a section is missing."""


def sheet_json_schema() -> dict[str, Any]:
    nullable = lambda t: {"type": [t, "null"]}  # noqa: E731
    player = {"type": "object", "additionalProperties": False, "required": ["number", "name", "position", "starter"],
              "properties": {"number": {"type": "integer"}, "name": {"type": "string"},
                             "position": nullable("string"), "starter": {"type": "boolean"}}}
    team = {"type": "string", "enum": ["home", "away"]}
    minute = {"type": ["integer", "string"]}

    def arr(props: dict[str, Any]) -> dict[str, Any]:
        return {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": list(props), "properties": props}}

    return {
        "type": "object", "additionalProperties": False,
        "required": ["home_team", "away_team", "lineups", "subs", "goals", "cards"],
        "properties": {
            "home_team": {"type": "string"}, "away_team": {"type": "string"},
            "lineups": {"type": "object", "additionalProperties": False, "required": ["home", "away"],
                        "properties": {"home": {"type": "array", "items": player},
                                       "away": {"type": "array", "items": player}}},
            "subs": arr({"minute": minute, "team": team, "off": {"type": "integer"}, "on": {"type": "integer"}}),
            "goals": arr({"minute": minute, "team": team, "scorer": {"type": "string"},
                          "assist": nullable("string"), "own_goal": {"type": "boolean"}}),
            "cards": arr({"minute": minute, "team": team, "player": {"type": "string"},
                          "colour": {"type": "string", "enum": ["yellow", "red"]}}),
        },
    }


class SheetReader:
    """OpenRouter chat-completions call with the rendered pages. ``client`` is injectable for tests."""

    def __init__(self, *, api_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 timeout: float | None = None, client: Any = None) -> None:
        self.api_url = (api_url if api_url is not None else os.environ.get("TAGGER_API_URL", "")).strip()
        self.api_key = (api_key if api_key is not None else os.environ.get("TAGGER_API_KEY", "")).strip()
        self.model = (model or os.environ.get("MATCHSHEET_MODEL") or DEFAULT_MODEL).strip()
        self.timeout = float(timeout or os.environ.get("TAGGER_TIMEOUT") or 120)
        self._client = client
        self.last_usage: dict[str, Any] = {}

    def enabled(self) -> bool:
        return bool(self.api_url and self.model)

    def endpoint(self) -> str:
        url = self.api_url.rstrip("/")
        return url if url.endswith("/chat/completions") else url + "/chat/completions"

    def build_request(self, pages: list[bytes], hint: str | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": "Read this match sheet." + (f" {hint}" if hint else "")}]
        for i, png in enumerate(pages):
            content.append({"type": "text", "text": f"page {i + 1}"})
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}})
        return {
            "model": self.model, "temperature": 0, "usage": {"include": True},
            "messages": [{"role": "system", "content": SHEET_PROMPT}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "match_sheet", "strict": True, "schema": sheet_json_schema()}},
        }

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(self.endpoint(), json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._client is None:
                client.close()

    @staticmethod
    def parse_response(payload: dict[str, Any]) -> dict[str, Any]:
        text = payload["choices"][0]["message"]["content"]
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        text = str(text).strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if fence:
            text = fence.group(1).strip()
        return json.loads(text)

    def read(self, pages: list[bytes], hint: str | None = None) -> dict[str, Any]:
        if not self.enabled():
            raise RuntimeError("match sheet reader is not configured (TAGGER_API_URL / MATCHSHEET_MODEL)")
        payload = self._post(self.build_request(pages, hint))
        self.last_usage = payload.get("usage") or {}
        return self.parse_response(payload)


# ---------------------------------------------------------------------------
# Draft / confirm storage
# ---------------------------------------------------------------------------


def save_draft(match_id: str, facts: dict[str, Any], *, source: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    clean, issues = validate_facts(facts)
    doc = {"status": "draft", "source": source, "facts": clean, "issues": issues, "raw": facts,
           "updated_at": time.time(), **(extra or {})}
    store.write_doc(match_id, "matchsheet", doc)
    return doc


def read_sheet(match_id: str, data: bytes, filename: str, *, reader: SheetReader | None = None) -> dict[str, Any]:
    pages = render_pages(data, filename)
    if not pages:
        raise ValueError("no pages in the uploaded match sheet")
    pages_dir = store.match_dir(match_id) / "matchsheet_pages"
    pages_dir.mkdir(exist_ok=True)
    for old in pages_dir.glob("*.png"):
        old.unlink()
    for i, png in enumerate(pages):
        (pages_dir / f"page{i + 1}.png").write_bytes(png)
    reader = reader or SheetReader()
    settings = store.read_doc(match_id, "settings", {}) or {}
    hint = None
    if settings.get("home_name") or settings.get("away_name"):
        hint = f"home = {settings.get('home_name') or '?'}, away = {settings.get('away_name') or '?'}."
    raw = reader.read(pages, hint)
    return save_draft(match_id, raw, source="vision", extra={"pages": len(pages), "model": reader.model,
                                                            "usage": reader.last_usage, "filename": filename})


def get_sheet(match_id: str) -> dict[str, Any] | None:
    doc = store.read_doc(match_id, "matchsheet", None)
    if doc is not None:
        doc = {**doc, "last_apply": store.read_doc(match_id, "matchsheet_apply", None)}
    return doc


def confirm_and_apply(match_id: str, facts: dict[str, Any], *, reviewer: str | None = None,
                      repo: EventRepo | None = None) -> dict[str, Any]:
    """The user confirmed (possibly edited) facts: store them as confirmed, then apply."""
    clean, issues = validate_facts(facts)
    prev = store.read_doc(match_id, "matchsheet", {}) or {}
    doc = {**prev, "status": "confirmed", "facts": clean, "issues": issues, "confirmed_at": time.time(),
           "confirmed_by": reviewer}
    store.write_doc(match_id, "matchsheet", doc)
    result = apply_facts(match_id, clean, repo=repo, reviewer=reviewer or "match sheet")
    return {"sheet": doc, **result}


__all__ = ["SheetReader", "apply_facts", "clock_anchors", "confirm_and_apply", "get_sheet", "lineup_doc",
           "on_pitch", "parse_minute", "read_sheet", "render_pages", "resolve_player", "save_draft", "validate_facts"]
