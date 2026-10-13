"""Phase 5: approximate shots-on-target from Phase 4 shots + film context.

Phase 4 keeps shot *counts* stable but leaves SoT on fact goals only (video SoT
was too noisy). This module re-labels `on_target` using film tags around each
selected shot:

- fact goals → always SoT
- nearby film ``Goal`` with a non-wide ball → goalmouth / save proxy
- nearby film ``Out`` with the ball on the goal line → deflection / corner after
  an on-target attempt (e.g. blocked/deflected for a corner)

Still approximate — not Opta. Designed to recover saves and close-range
deflections without flipping every high-score shot to SoT.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from statman.match_pack import store
from statman.match_pack.shots import PHASE as PHASE4, merge_shots_into_sheet

PHASE = "match-pack-phase5"
ProgressCb = Callable[[dict[str, Any]], None]

DEFAULT_WINDOW_SEC = 6.0
# Ball y-distance to nearest frame edge (broadcast goal line proxy).
OUT_NEAR_GOAL_LINE = 16.0
SHOT_GD_FOR_OUT = 50.0
# Film "Goal" tags are often saves; reject obvious wide misses.
GOAL_TAG_LAT_MAX = 0.78
GOAL_TAG_GD_MAX = 60.0
DEFAULT_FRAME_W = 1280.0
DEFAULT_FRAME_H = 720.0


def _frame_size(meta: dict[str, Any], tracking: dict[str, Any] | None) -> tuple[float, float]:
    video = meta.get("video") or {}
    tw = (tracking or {}).get("frame_w") or (tracking or {}).get("width")
    th = (tracking or {}).get("frame_h") or (tracking or {}).get("height")
    fw = float(tw or video.get("width") or DEFAULT_FRAME_W)
    fh = float(th or video.get("height") or DEFAULT_FRAME_H)
    return fw, fh


def _goal_dist(y: float, frame_h: float) -> float:
    return float(min(y, frame_h - y))


def _lateral(x: float, frame_w: float) -> float:
    return float(abs(x - frame_w / 2.0) / max(frame_w / 2.0, 1.0))


def classify_shot_sot(
    shot: dict[str, Any],
    film_events: list[dict[str, Any]],
    *,
    frame_w: float = DEFAULT_FRAME_W,
    frame_h: float = DEFAULT_FRAME_H,
    window_sec: float = DEFAULT_WINDOW_SEC,
) -> tuple[bool, str | None]:
    """Return (on_target, reason) for one Phase-4 selected shot."""
    if shot.get("fact_goal"):
        return True, "fact_goal"

    t = float(shot.get("time_sec") or 0.0)
    shot_gd = float(shot.get("goal_dist") if shot.get("goal_dist") is not None else 999.0)
    nearby = [
        e
        for e in film_events
        if e.get("ball_xy")
        and abs(float(e.get("time_sec") or 0.0) - t) <= window_sec
    ]

    # Save / goalmouth: spotter "Goal" with ball not stuck wide of the posts.
    for e in nearby:
        if e.get("label") != "Goal":
            continue
        bx, by = e["ball_xy"]
        lat = _lateral(float(bx), frame_w)
        gd = _goal_dist(float(by), frame_h)
        if lat <= GOAL_TAG_LAT_MAX and gd <= GOAL_TAG_GD_MAX:
            return True, "film_goalmouth_or_save"

    # Deflection / corner: Out with ball on the goal line near a close shot.
    if shot_gd <= SHOT_GD_FOR_OUT:
        for e in nearby:
            if e.get("label") != "Out":
                continue
            bx, by = e["ball_xy"]
            if _goal_dist(float(by), frame_h) <= OUT_NEAR_GOAL_LINE:
                return True, "deflected_or_corner"

    return False, None


def apply_sot_to_shots(
    shot_result: dict[str, Any],
    film_events: list[dict[str, Any]],
    *,
    frame_w: float = DEFAULT_FRAME_W,
    frame_h: float = DEFAULT_FRAME_H,
    window_sec: float = DEFAULT_WINDOW_SEC,
) -> dict[str, Any]:
    """Copy a Phase-4 shot result and rewrite on_target / SoT totals."""
    out = dict(shot_result)
    selected: list[dict[str, Any]] = []
    for e in shot_result.get("selected") or []:
        row = dict(e)
        on, reason = classify_shot_sot(
            row,
            film_events,
            frame_w=frame_w,
            frame_h=frame_h,
            window_sec=window_sec,
        )
        row["on_target"] = bool(on)
        row["sot_reason"] = reason
        selected.append(row)

    def _count(side: str) -> dict[str, int]:
        rows = [e for e in selected if e.get("team") == side]
        return {
            "shots": len(rows),
            "shots_on_target": sum(1 for e in rows if e.get("on_target")),
        }

    out["selected"] = selected
    out["totals"] = {
        "home": _count("home"),
        "away": _count("away"),
        "match": {
            "shots": len(selected),
            "shots_on_target": sum(1 for e in selected if e.get("on_target")),
        },
    }
    out["phase"] = PHASE
    out["method"] = "film-sot-goalmouth-v1"
    out["sot"] = {
        "window_sec": window_sec,
        "out_near_goal_line": OUT_NEAR_GOAL_LINE,
        "goal_tag_lat_max": GOAL_TAG_LAT_MAX,
        "frame_w": frame_w,
        "frame_h": frame_h,
    }
    out["warning"] = (
        "Approximate SoT: fact goals + film Goal (non-wide) as save/goalmouth + "
        "Out on the goal line near a close shot (deflection/corner). Not Opta."
    )
    return out


def merge_sot_into_sheet(sheet: dict[str, Any], shot_result: dict[str, Any]) -> dict[str, Any]:
    """Reuse Phase-4 board merge, then stamp Phase-5 coverage / provenance."""
    out = merge_shots_into_sheet(sheet, shot_result)
    # merge_shots_into_sheet stamps phase4 — overwrite SoT provenance + coverage.
    teams = []
    for team in out.get("teams") or []:
        t = dict(team)
        prov = dict(t.get("provenance") or {})
        if "shots_on_target" in prov:
            prov["shots_on_target"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": (
                    "SoT ≈ fact goals + film goalmouth/save + deflection-to-corner"
                ),
            }
        if "shots" in prov:
            # Keep shot *counts* attributed to Phase 4.
            shot_prov = dict(prov["shots"])
            shot_prov.setdefault("phase", PHASE4)
            prov["shots"] = shot_prov
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams

    shots_block = dict(out.get("shots") or {})
    shots_block["phase"] = PHASE
    shots_block["sot"] = shot_result.get("sot")
    out["shots"] = shots_block

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    totals = shot_result.get("totals") or {}
    cov["phase5"] = {
        "shots_home": (totals.get("home") or {}).get("shots"),
        "shots_away": (totals.get("away") or {}).get("shots"),
        "sot_home": (totals.get("home") or {}).get("shots_on_target"),
        "sot_away": (totals.get("away") or {}).get("shots_on_target"),
        "method": shot_result.get("method"),
    }
    # Keep phase4 shot counts; refresh SoT mirrors used by the UI banner.
    phase4 = dict(cov.get("phase4") or {})
    phase4["sot_home"] = (totals.get("home") or {}).get("shots_on_target")
    phase4["sot_away"] = (totals.get("away") or {}).get("shots_on_target")
    cov["phase4"] = phase4
    phase3 = dict(cov.get("phase3") or {})
    phase3["sot_home"] = phase4.get("sot_home")
    phase3["sot_away"] = phase4.get("sot_away")
    cov["phase3"] = phase3
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film_plus_tracking_plus_shots_plus_sot"
    note = (src.get("note") or "").rstrip()
    # Avoid stacking duplicate Phase 5 notes on re-runs.
    if "Phase 5:" not in note:
        src["note"] = (
            f"{note} Phase 5: approximate SoT (goalmouth/save + deflection/corner)."
        ).strip()
    out["source"] = src
    return out


def run_phase5(pack_id: str, *, on_progress: ProgressCb | None = None) -> dict[str, Any]:
    """Classify SoT on an existing Phase-4 shot list and merge onto the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    shots_path = store.pack_dir(pack_id) / "shots.json"
    events_path = store.pack_dir(pack_id) / "film_events.json"
    if not shots_path.exists():
        raise ValueError("Run Phase 4 shot scoring first")
    if not events_path.exists():
        raise ValueError("Run Phase 2 film analyze first")

    meta["phase5"] = {
        "status": "running",
        "progress": {"stage": "classify_sot", "pct": 10},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "classify_sot", "pct": 10})

    shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
    film_events = json.loads(events_path.read_text(encoding="utf-8"))
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    tracking = (
        json.loads(tracking_path.read_text(encoding="utf-8"))
        if tracking_path.exists()
        else {}
    )
    fw, fh = _frame_size(meta, tracking)

    result = apply_sot_to_shots(shot_result, film_events, frame_w=fw, frame_h=fh)
    result["created_at"] = time.time()
    result["from_phase4_method"] = shot_result.get("method")
    shots_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    if on_progress:
        on_progress({"stage": "merge_sheet", "pct": 80})

    # Rebuild board from Phase 3 sheet base + updated shots/SoT.
    from statman.match_pack.phase3 import apply_phase3_to_sheet

    meta = apply_phase3_to_sheet(pack_id)
    sheet = merge_sot_into_sheet(meta.get("sheet") or {}, result)
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["shots_path"] = str(shots_path)
    meta["status"] = "phase5_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    meta["phase5"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "totals": result.get("totals"),
        "method": result.get("method"),
        "error": None,
        "updated_at": time.time(),
    }
    # Keep phase4 totals mirror in sync for older UI bits.
    p4 = dict(meta.get("phase4") or {})
    if p4:
        p4["totals"] = result.get("totals")
        meta["phase4"] = p4
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
