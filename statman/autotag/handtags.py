"""Load hand-tag text files (the analyst ``tags60`` format) as app events.

Line format::

    CLOCK|TEAM|CODE|Player|NUM|OUTCOME|x1,y1|x2,y2|detail|conf

x/y are 0..100 from the acting team's view (x=100 = the goal it attacks).
Lines starting with ``#`` are comments; ``GAP`` lines become ``gap`` events
(footage with nothing taggable). Files are named ``MM-MM.txt`` (match minute
range). The same file rules as the hand pipeline (``build3.py``) apply:

* when two consecutive files overlap (e.g. ``40-46`` and ``45-49``), events
  from the overlap come from the later file only;
* exact duplicates (same clock, team, code, start and end point) are dropped.

Events go through the same ``from_code_event`` + ``normalize_event`` path as
the analyst-code tagger, so the stats code sees exactly what a tagged clip
would produce. Used for validation against the hand pipeline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from statman.autotag.taxonomy import clock_to_seconds, from_code_event, normalize_event

OK_OUTCOMES = {"1", "success", "successful", "completed", "complete", "goal"}
FAIL_OUTCOMES = {"0", "fail", "failed", "unsuccessful", "incomplete"}
SHOT_OUTCOMES = {"goal": "goal", "saved": "on", "on": "on", "missed": "off", "off": "off", "blocked": "blocked",
                 "outcome_blocked": "blocked", "post": "post", "fail": "off", "0": "off"}
_RANGE = re.compile(r"^(\d+)-(\d+)$")


def _pt(text: str) -> tuple[float, float] | None:
    parts = text.split(",")
    if len(parts) != 2 or not parts[0].strip():
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _outcome(code: str, raw: str) -> str | None:
    o = raw.strip().lower()
    if not o:
        return None
    if code == "SHOT":
        return SHOT_OUTCOMES.get(o)
    if o in {"yellow", "red"}:
        return o
    if o in OK_OUTCOMES:
        return "success"
    if o in FAIL_OUTCOMES:
        return "fail"
    return None


def parse_line(line: str, teams: dict[str, str], batch: str = "") -> dict[str, Any] | None:
    line = line.rstrip("\n")
    if not line.strip() or line.startswith("#"):
        return None
    p = [x.strip() for x in line.split("|")]
    if "GAP" in p[:3]:
        span = next((x for x in p if re.match(r"^\d+:\d+-\d+:\d+$", x)), None)
        start = clock_to_seconds(span.split("-")[0]) if span else clock_to_seconds(p[0])
        if start is None:
            return None
        return {"type": "gap", "team": None, "t_match_seconds": start, "code": "GAP", "detail": span,
                "attributes": {}, "confidence": 1.0, "batch": batch, "clock": span}
    if len(p) < 6 or p[1] not in teams or not re.match(r"^\d+:\d+$", p[0]):
        return None
    p += [""] * (10 - len(p))
    code = p[2].upper()
    a, b = _pt(p[6]), _pt(p[7])
    try:
        conf = float(p[9]) if p[9] else 1.0
    except ValueError:
        conf = 1.0
    raw = {
        "code": code, "team": teams[p[1]], "player": p[3] or None, "shirt": int(p[4]) if p[4].isdigit() else None,
        "outcome": _outcome(code, p[5]), "x1": a[0] if a else None, "y1": a[1] if a else None,
        "x2": b[0] if b else None, "y2": b[1] if b else None, "detail": p[8] or None, "confidence": conf,
        "t_match_seconds": clock_to_seconds(p[0]),
    }
    coded = from_code_event(raw)
    if coded is None:
        return None
    ev, issues = normalize_event(coded)
    if ev is None:
        return None
    ev.update({"batch": batch, "clock": p[0], "issues": issues, "_key": (p[0], p[1], code, p[6], p[7])})
    return ev


def _range(path: Path) -> tuple[int, int] | None:
    m = _RANGE.match(path.stem)
    return (int(m.group(1)), int(m.group(2))) if m else None


def load_files(paths: Iterable[str | Path], teams: dict[str, str], *, review_status: str = "confirmed",
               supplements: Iterable[tuple[str | Path, Callable[[dict[str, Any]], bool]]] = ()) -> list[dict[str, Any]]:
    """Parse ``MM-MM.txt`` files (sorted by start minute) into app events.

    ``supplements``: extra (path, keep) pairs, e.g. events an analyst header
    says to keep from an older pass; only lines where ``keep(event)`` is true
    are added (still de-duplicated).
    """

    files = sorted((Path(p) for p in paths if _range(Path(p))), key=lambda p: _range(p))
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def add(ev: dict[str, Any]) -> None:
        key = ev.pop("_key", None)
        if key is not None:
            if key in seen:
                return
            seen.add(key)
        ev["review_status"] = review_status
        ev["id"] = len(out) + 1
        out.append(ev)

    for i, f in enumerate(files):
        lo, hi = _range(f)
        nxt = _range(files[i + 1]) if i + 1 < len(files) else None
        cut = nxt[0] * 60 if nxt and nxt[0] < hi else None  # overlap -> later file wins
        for line in f.read_text(encoding="utf-8").splitlines():
            ev = parse_line(line, teams, f.stem)
            if ev is None or (cut is not None and ev["t_match_seconds"] >= cut):
                continue
            add(ev)
    for path, keep in supplements:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            ev = parse_line(line, teams, Path(path).stem)
            if ev is not None and keep(ev):
                add(ev)
    return out
