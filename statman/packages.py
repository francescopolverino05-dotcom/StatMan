"""Stats packages: load, store, view and export finished match stats.

StatMan does not tag or detect anything. A *package* is what is produced
elsewhere (Grok Bot, a spreadsheet, another tool) and loaded here to be viewed
and exported:

* ``<match>_team.csv``     ``metric,<home>,<away>`` (optional ``status,reason`` columns)
* ``<match>_players.csv``  one row per player, any columns (``team``, ``player`` ... )
* ``<match>_stats.html``   optional human report (title, summary and notes are read from it;
                           the file itself is kept and shown sandboxed)
* ``<match>_shots.csv``    optional shot list
* ``stats.json``           optional, only ``match`` / ``score`` are read

Files are told apart by name and by header, so the user can drop the whole
folder in one go. ``*_team_stats.csv`` / ``*_player_stats.csv`` duplicates are
accepted and ignored when a ``_team.csv`` / ``_players.csv`` is present.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from statman.persistence.mirror import register as _register_collection

ROOT = Path(__file__).resolve().parent.parent / ".data" / "packages"
MAX_FILE_BYTES = 8_000_000
MAX_ROWS = 5000

_register_collection(
    "packages",
    lambda: ROOT,
    include=lambda key: key.count("/") == 1 and key.endswith(("/package.json", "/meta.json")),
)

# Section order and titles for the team table (first matching rule wins).
SECTIONS: list[tuple[str, str, re.Pattern[str]]] = [
    ("ppda", "PPDA (pressing)", re.compile(r"\bppda\b", re.I)),
    ("progressive", "Progressive passes", re.compile(r"progressive", re.I)),
    ("xg", "Expected goals", re.compile(r"\bx\s?g\b|expected goals", re.I)),
    ("possession", "Possession", re.compile(r"possession", re.I)),
    ("shooting", "Shooting", re.compile(r"^shot|\bshots?\b", re.I)),
    ("passing", "Passing", re.compile(r"pass", re.I)),
    (
        "setpieces",
        "Corners, fouls, cards, offsides",
        re.compile(r"corner|foul|card|offside", re.I),
    ),
    (
        "defence",
        "Defence",
        re.compile(r"interception|tackle|recover|clearance|block|duel|aerial|save", re.I),
    ),
]
SECTION_ORDER = ["possession", "passing", "progressive", "shooting", "xg", "setpieces", "ppda", "defence", "other"]
SECTION_TITLES = {k: t for k, t, _ in SECTIONS} | {"other": "Other"}


def classify_metric(label: str) -> str:
    for key, _title, pat in SECTIONS:
        if pat.search(label):
            return key
    return "other"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _read_csv(text: str) -> list[list[str]]:
    text = text.lstrip("\ufeff")
    sample = text[:4096]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        first = sample.split("\n", 1)[0]
        delimiter = max(",;\t", key=first.count)
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    return [r for r in rows if any(c for c in r)]


def _num(value: str) -> float | None:
    v = value.strip().replace("%", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def parse_team_csv(text: str) -> dict[str, Any]:
    rows = _read_csv(text)
    if len(rows) < 2 or len(rows[0]) < 3:
        raise ValueError("Team CSV needs a header 'metric,<team A>,<team B>' and at least one row")
    header = rows[0]
    extra_cols = [i for i, h in enumerate(header[3:], start=3) if h.lower() in ("status", "reason", "note", "notes")]
    out_rows = []
    for r in rows[1:MAX_ROWS]:
        r = r + [""] * (len(header) - len(r))
        item = {
            "metric": r[0],
            "home": r[1],
            "away": r[2],
            "section": classify_metric(r[0]),
        }
        for i in extra_cols:
            if r[i]:
                item[header[i].lower()] = r[i]
        out_rows.append(item)
    return {"teams": [header[1], header[2]], "extra_columns": [header[i].lower() for i in extra_cols], "rows": out_rows}


def parse_players_csv(text: str) -> dict[str, Any]:
    rows = _read_csv(text)
    if len(rows) < 2:
        raise ValueError("Players CSV needs a header row and at least one player")
    header = rows[0]
    body = [(r + [""] * len(header))[: len(header)] for r in rows[1:MAX_ROWS]]
    return {"columns": header, "rows": body}


def parse_shots_csv(text: str) -> dict[str, Any]:
    return parse_players_csv(text)


class _HtmlInfo(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1 = ""
        self.paragraphs: list[str] = []
        self.items: list[str] = []
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("title", "h1", "p", "li"):
            self._stack.append(tag)
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if self._stack and self._stack[-1] == tag:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._stack.pop()
            if text:
                if tag == "title" and not self.title:
                    self.title = text
                elif tag == "h1" and not self.h1:
                    self.h1 = text
                elif tag == "p":
                    self.paragraphs.append(text)
                elif tag == "li":
                    self.items.append(text)
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._stack and not self._skip:
            self._buf.append(data)


def parse_report_html(text: str) -> dict[str, Any]:
    p = _HtmlInfo()
    try:
        p.feed(text)
    except Exception:  # noqa: BLE001 - malformed HTML must never block a load
        pass
    return {
        "title": p.h1 or p.title,
        "summary": p.paragraphs[0] if p.paragraphs else "",
        "notes": p.items[:60],
    }


# --------------------------------------------------------------------------
# classification of uploaded files
# --------------------------------------------------------------------------


def _kind(name: str, data: bytes) -> str:
    low = name.lower()
    stem = Path(low).name
    if stem.endswith((".html", ".htm")):
        return "html"
    if stem.endswith(".json"):
        return "json"
    if not stem.endswith((".csv", ".txt", ".tsv")):
        return "unknown"
    if "shot" in stem:
        return "shots"
    if "player" in stem:
        return "players"
    if "team" in stem:
        return "team"
    head = _decode(data[:4096]).lstrip("\ufeff").split("\n", 1)[0].lower()
    if head.startswith("metric") or head.startswith("stat"):
        return "team"
    if "player" in head:
        return "players"
    if "xg" in head and ("clock" in head or "outcome" in head):
        return "shots"
    return "unknown"


def _prefer(cands: list[tuple[str, bytes]], good_suffixes: tuple[str, ...]) -> tuple[str, bytes]:
    for name, data in cands:
        if Path(name.lower()).name.endswith(good_suffixes):
            return name, data
    return cands[0]


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return s[:60] or "match"


def build_package(files: list[tuple[str, bytes]], title: str | None = None) -> dict[str, Any]:
    by_kind: dict[str, list[tuple[str, bytes]]] = {}
    ignored: list[str] = []
    for name, data in files:
        k = _kind(name, data)
        if k == "unknown":
            ignored.append(name)
        else:
            by_kind.setdefault(k, []).append((name, data))
    if "team" not in by_kind and "players" not in by_kind:
        raise ValueError(
            "No team or players CSV found. Add <match>_team.csv (metric,teamA,teamB) "
            "and/or <match>_players.csv."
        )
    pkg: dict[str, Any] = {"team": None, "players": None, "shots": None, "report_html": None, "notes": [], "summary": ""}
    used: list[str] = []
    stem_hint = ""
    if "team" in by_kind:
        name, data = _prefer(by_kind["team"], ("_team.csv",))
        pkg["team"] = parse_team_csv(_decode(data))
        used.append(name)
        stem_hint = re.sub(r"_team(_stats)?\.csv$", "", Path(name).name, flags=re.I)
    if "players" in by_kind:
        name, data = _prefer(by_kind["players"], ("_players.csv",))
        pkg["players"] = parse_players_csv(_decode(data))
        used.append(name)
        stem_hint = stem_hint or re.sub(r"_players?(_stats)?\.csv$", "", Path(name).name, flags=re.I)
    if "shots" in by_kind:
        name, data = by_kind["shots"][0]
        pkg["shots"] = parse_shots_csv(_decode(data))
        used.append(name)
    meta_title = ""
    if "html" in by_kind:
        name, data = by_kind["html"][0]
        html = _decode(data)
        info = parse_report_html(html)
        pkg["report_html"] = html
        pkg["notes"] = info["notes"]
        pkg["summary"] = info["summary"]
        meta_title = info["title"]
        used.append(name)
    if "json" in by_kind:
        for name, data in by_kind["json"]:
            try:
                j = json.loads(_decode(data))
            except ValueError:
                continue
            if isinstance(j, dict) and isinstance(j.get("match"), str):
                meta_title = j["match"]
                pkg["score"] = j.get("score")
                used.append(name)
                break
    teams = pkg["team"]["teams"] if pkg["team"] else []
    fallback = f"{teams[0]} vs {teams[1]}" if len(teams) == 2 else (stem_hint or "Match")
    pkg["title"] = (title or "").strip() or meta_title or fallback
    pkg["slug"] = _slug(stem_hint or pkg["title"])
    pkg["teams"] = teams
    pkg["files_used"] = used
    pkg["files_ignored"] = ignored
    return pkg


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


def _dir(package_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", package_id):
        raise ValueError("bad package id")
    return ROOT / package_id


def _summary(pkg: dict[str, Any]) -> dict[str, Any]:
    return {
        "package_id": pkg["package_id"],
        "title": pkg["title"],
        "teams": pkg.get("teams") or [],
        "created_at": pkg["created_at"],
        "has_team": bool(pkg.get("team")),
        "players": len(pkg["players"]["rows"]) if pkg.get("players") else 0,
        "has_report": bool(pkg.get("report_html")),
        "has_shots": bool(pkg.get("shots")),
    }


def create_package(files: list[tuple[str, bytes]], title: str | None = None) -> dict[str, Any]:
    pkg = build_package(files, title=title)
    pkg["package_id"] = uuid.uuid4().hex[:12]
    pkg["created_at"] = time.time()
    d = _dir(pkg["package_id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps(pkg, ensure_ascii=False), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(_summary(pkg), ensure_ascii=False), encoding="utf-8")
    return public_view(pkg)


def public_view(pkg: dict[str, Any]) -> dict[str, Any]:
    """Package without the (potentially large) HTML body; add section layout."""
    out = {k: v for k, v in pkg.items() if k != "report_html"}
    out["has_report"] = bool(pkg.get("report_html"))
    out["section_order"] = SECTION_ORDER
    out["section_titles"] = SECTION_TITLES
    return out


def get_package(package_id: str, *, full: bool = True) -> dict[str, Any] | None:
    try:
        path = _dir(package_id) / "package.json"
    except ValueError:
        return None
    if not path.exists():
        return None
    pkg = json.loads(path.read_text(encoding="utf-8"))
    return pkg if full else public_view(pkg)


def list_packages(limit: int = 50) -> list[dict[str, Any]]:
    if not ROOT.exists():
        return []
    rows = []
    for p in ROOT.iterdir():
        m = p / "meta.json"
        if p.is_dir() and m.exists():
            try:
                rows.append(json.loads(m.read_text(encoding="utf-8")))
            except ValueError:
                continue
    rows.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return rows[:limit]


def delete_package(package_id: str) -> bool:
    import shutil

    try:
        d = _dir(package_id)
    except ValueError:
        return False
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


def _csv_text(header: list[str], rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def team_csv(pkg: dict[str, Any]) -> str:
    team = pkg.get("team")
    if not team:
        raise ValueError("no team table")
    extras = team.get("extra_columns") or []
    header = ["metric", *team["teams"], *extras]
    rows = [[r["metric"], r["home"], r["away"], *[r.get(c, "") for c in extras]] for r in team["rows"]]
    return _csv_text(header, rows)


def players_csv(pkg: dict[str, Any]) -> str:
    pl = pkg["players"]
    return _csv_text(pl["columns"], pl["rows"])


def shots_csv(pkg: dict[str, Any]) -> str:
    sh = pkg["shots"]
    return _csv_text(sh["columns"], sh["rows"])
