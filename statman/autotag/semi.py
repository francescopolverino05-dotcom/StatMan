"""Semi-automatic tagging: the analyst reviews detector moments (or tags from scratch) and confirms each event.

Session doc (``semi`` in the match store)::

    {"settings": {"segments": [{"video_start": 0, "match_start": 0}], "home_name", "away_name",
                  "home_attacks_right_first_half": true},
     "moments": [{"t_video", "team_suggestion", "score", "kind"}],     # detector output, never counted
     "items":   [{"id", "t_video", "status": "todo"|"done"|"deleted", "from_moment": bool,
                  "team_suggestion", "code", "team", "shirt", "outcome", "x1", "y1", "x2", "y2", "detail"}]}

Coordinates in items are already 0..100 from the acting team's view (x=100 = the goal it attacks), the hand-tag
convention; the page converts its on-screen pitch clicks. Every ``done`` item is turned into a ``tags60`` line and
parsed with :func:`statman.autotag.handtags.parse_line`, i.e. exactly the hand-tag path, then stored as a
``confirmed`` human event marked ``review_reason=['semi']`` (replacing the previous semi events). Detector team guesses are only
``team_suggestion`` and never reach the stats unless the analyst confirms a team.
"""
from __future__ import annotations

import csv
import io
import time
from typing import Any

from statman.autotag import store
from statman.autotag.handtags import parse_line
from statman.autotag.repo import get_repo
from statman.autotag.taxonomy import CODES

MARK = "semi"  # stored as source=human with review_reason [semi] (DB allows ai|human)
DOC = "semi"
STATUSES = ("todo", "done", "deleted")
# Codes offered in the page (UI label -> analyst code); all must be known to the taxonomy.
UI_CODES = ["PASS", "CROSS", "SHOT", "TACKLE", "INTERCEPT", "CLEAR", "FOUL", "THROW", "CORNER", "FK", "GOALKICK",
            "SAVE", "RECOVERY", "DUEL", "AERIAL", "LOST", "GK_PASS", "CARD"]
SHOT_OUTCOMES = ("on", "off", "blocked", "goal", "post")
assert all(c in CODES for c in UI_CODES)


def default_settings() -> dict[str, Any]:
    return {"segments": [{"video_start": 0.0, "match_start": 0.0}], "home_name": "Home", "away_name": "Away",
            "home_attacks_right_first_half": True}


def get_session(match_id: str) -> dict[str, Any]:
    doc = store.read_doc(match_id, DOC, None) or {}
    return {"settings": {**default_settings(), **(doc.get("settings") or {})},
            "moments": doc.get("moments") or [], "items": doc.get("items") or [],
            "updated_at": doc.get("updated_at")}


def video_to_match(t_video: float, segments: list[dict[str, Any]]) -> float:
    segs = sorted(segments or [{"video_start": 0, "match_start": 0}], key=lambda s: float(s["video_start"]))
    seg = segs[0]
    for s in segs:
        if float(s["video_start"]) <= t_video:
            seg = s
    return float(seg["match_start"]) + (t_video - float(seg["video_start"]))


def clock(t_match: float) -> str:
    s = max(0, int(round(t_match)))
    return f"{s // 60:02d}:{s % 60:02d}"


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    v = float(v)
    if not 0 <= v <= 100:
        raise ValueError(f"coordinate {v} outside 0..100")
    return round(v, 1)


def clean_item(it: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(it, dict):
        raise ValueError("item must be an object")
    status = it.get("status") or "todo"
    if status not in STATUSES:
        raise ValueError(f"bad status {status}")
    code = (str(it.get("code") or "").upper() or None)
    if code and code not in CODES:
        raise ValueError(f"unknown event code {code}")
    team = it.get("team") or None
    if team not in (None, "home", "away"):
        raise ValueError("team must be home|away")
    shirt = it.get("shirt")
    shirt = int(shirt) if shirt not in (None, "") else None
    out = {"id": str(it.get("id") or f"i{time.time_ns()}"), "t_video": round(float(it["t_video"]), 2),
           "status": status, "from_moment": bool(it.get("from_moment")),
           "team_suggestion": it.get("team_suggestion") if it.get("team_suggestion") in ("home", "away") else None,
           "code": code, "team": team, "shirt": shirt, "outcome": (str(it.get("outcome") or "").lower() or None),
           "detail": str(it.get("detail") or "")[:200].replace("|", "/") or None}
    for k in ("x1", "y1", "x2", "y2"):
        out[k] = _num(it.get(k))
    if status == "done":
        if not code or not team:
            raise ValueError(f"item at {out['t_video']}s: a confirmed event needs a type and a team")
    return out


def to_line(it: dict[str, Any], settings: dict[str, Any]) -> str:
    """The item as a hand-tag (tags60) line: CLOCK|TEAM|CODE|Player|NUM|OUTCOME|x1,y1|x2,y2|detail|conf."""
    names = {"home": settings.get("home_name") or "Home", "away": settings.get("away_name") or "Away"}
    t = video_to_match(it["t_video"], settings.get("segments"))
    pt = lambda a, b: f"{a:g},{b:g}" if a is not None and b is not None else ""  # noqa: E731
    return "|".join([clock(t), names[it["team"]], it["code"], "", "" if it["shirt"] is None else str(it["shirt"]),
                     it["outcome"] or "", pt(it["x1"], it["y1"]), pt(it["x2"], it["y2"]), it.get("detail") or "", "1"])


def to_events(items: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    names = {settings.get("home_name") or "Home": "home", settings.get("away_name") or "Away": "away"}
    out = []
    for it in items:
        if it["status"] != "done":
            continue
        ev = parse_line(to_line(it, settings), names, "semi")
        if ev is None:
            raise ValueError(f"item at {it['t_video']}s could not be parsed")
        ev.pop("_key", None)
        t = video_to_match(it["t_video"], settings.get("segments"))
        ev.update({"t_match_seconds": t, "video_ts_seconds": it["t_video"], "review_status": "confirmed",
                   "source": "human", "confidence": 1.0, "issues": [], "review_reason": [], "clip_ids": [],
                   "period": 1 if t < 45 * 60 else 2})
        out.append(ev)
    return out


def save_session(match_id: str, body: dict[str, Any], repo=None) -> dict[str, Any]:
    """Validate + store the session, then sync confirmed items into the event store as authoritative tags."""
    cur = get_session(match_id)
    settings = {**cur["settings"], **(body.get("settings") or {})}
    for s in settings.get("segments") or []:
        float(s["video_start"]); float(s["match_start"])
    items = [clean_item(i) for i in (body["items"] if "items" in body else cur["items"])]
    items.sort(key=lambda i: i["t_video"])
    events = to_events(items, settings)
    doc = {"settings": settings, "moments": body.get("moments", cur["moments"]), "items": items,
           "updated_at": time.time()}
    store.write_doc(match_id, DOC, doc)
    repo = repo or get_repo()
    repo.replace_marked_events(match_id, MARK, events)
    sheet = store.read_doc(match_id, "matchsheet", None)
    if sheet and sheet.get("status") == "confirmed" and sheet.get("facts"):
        from statman.autotag.matchsheet import apply_facts
        apply_facts(match_id, sheet["facts"], repo=repo, reviewer="match sheet (re-applied after semi save)")
    return {**doc, "confirmed": len(events)}


def import_moments(match_id: str, payload: Any, *, replace_todo: bool = True) -> dict[str, Any]:
    """Detector JSON (``statman.detect.cli`` output or a list of moments) -> todo items. Times are video seconds."""
    rows = payload.get("moments") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("expected {moments: [...]} or a list")
    moments = []
    for m in rows:
        if not isinstance(m, dict) or m.get("t") is None and m.get("t_video") is None:
            raise ValueError("each moment needs t (video seconds)")
        team = m.get("team_suggestion", m.get("possession_team") or m.get("team"))
        moments.append({"t_video": round(float(m.get("t_video", m.get("t"))), 2), "kind": m.get("kind"),
                        "score": m.get("score"), "team_suggestion": team if team in ("home", "away") else None})
    cur = get_session(match_id)
    items = [i for i in cur["items"] if not (replace_todo and i["status"] == "todo" and i.get("from_moment"))]
    for k, m in enumerate(sorted(moments, key=lambda m: m["t_video"])):
        if any(abs(i["t_video"] - m["t_video"]) < 0.3 for i in items):
            continue
        items.append({"id": f"m{k}_{int(m['t_video'] * 100)}", "t_video": m["t_video"], "status": "todo",
                      "from_moment": True, "team_suggestion": m["team_suggestion"]})
    return save_session(match_id, {"moments": moments, "items": items})


def export_csv(match_id: str) -> str:
    s = get_session(match_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["clock", "match_seconds", "video_seconds", "team", "team_name", "code", "shirt", "outcome",
                "x1", "y1", "x2", "y2", "detail"])
    names = {"home": s["settings"]["home_name"], "away": s["settings"]["away_name"]}
    for it in s["items"]:
        if it["status"] != "done":
            continue
        t = video_to_match(it["t_video"], s["settings"]["segments"])
        w.writerow([clock(t), round(t, 2), it["t_video"], it["team"], names[it["team"]], it["code"], it["shirt"],
                    it["outcome"], it["x1"], it["y1"], it["x2"], it["y2"], it.get("detail") or ""])
    return buf.getvalue()


def export_tags(match_id: str) -> str:
    s = get_session(match_id)
    return "\n".join(to_line(i, s["settings"]) for i in s["items"] if i["status"] == "done") + "\n"
