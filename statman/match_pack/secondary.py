"""Phase 8: fill progressive passes, aerials, interceptions, clearances.

Board-fill proxies from film tags + possession timeline (same spirit as Phase 7).
Still approximate — not Opta. Leaves xG / PPDA pending for later models.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any, Callable

import numpy as np

from statman.match_pack import store
from statman.match_pack.actions import (
    _possession_flips,
    _rebuild_sheet_through_phase6,
    _team_at,
    estimate_pass_completion,
    merge_actions_into_sheet,
    score_tackle_candidates,
    select_tackles,
)
from statman.match_pack.actions import PHASE as PHASE7
from statman.match_pack.tracking import debounce_film_events

PHASE = "match-pack-phase8"
ProgressCb = Callable[[dict[str, Any]], None]

PASS_PROG_LABELS = {"Pass", "High Pass", "Cross"}
DEFAULT_FRAME_W = 1280.0
DEFAULT_FRAME_H = 720.0
DEFAULT_MAX_INT_PER_90 = 14.0
DEFAULT_MAX_CLR_PER_90 = 16.0
DEFAULT_MIN_GAP_SEC = 25.0


def _frame_size(meta: dict[str, Any], tracking: dict[str, Any]) -> tuple[float, float]:
    video = meta.get("video") or {}
    fw = float(
        tracking.get("frame_w")
        or tracking.get("width")
        or video.get("width")
        or DEFAULT_FRAME_W
    )
    fh = float(
        tracking.get("frame_h")
        or tracking.get("height")
        or video.get("height")
        or DEFAULT_FRAME_H
    )
    return fw, fh


def _goal_dist(y: float, frame_h: float) -> float:
    return float(min(y, frame_h - y))


def _handler_ball_dist(e: dict[str, Any]) -> float | None:
    b = e.get("ball_xy")
    h = e.get("handler_xy")
    if not b or not h:
        return None
    return float(np.hypot(float(b[0]) - float(h[0]), float(b[1]) - float(h[1])))


def _possession_held(
    timeline: list[dict[str, Any]], t: float, side: str
) -> bool:
    later = [_team_at(timeline, t + dt) for dt in (1.5, 2.5, 3.5, 4.5)]
    later = [x for x in later if x in {"home", "away"}]
    if not later:
        return False
    return sum(1 for x in later if x == side) >= (len(later) + 1) // 2


def estimate_progressive_passes(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    frame_h: float = DEFAULT_FRAME_H,
    debounce: bool = True,
) -> dict[str, Any]:
    """Long / high completed passes as progressive proxy (no pitch calibration)."""
    events = debounce_film_events(film_events) if debounce else list(film_events)
    long_thresh = 0.22 * frame_h
    sides = {
        s: {
            "progressive_passes_attempted": 0,
            "progressive_passes_completed": 0,
        }
        for s in ("home", "away")
    }
    for e in events:
        label = e.get("label")
        if label not in PASS_PROG_LABELS:
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t)
        if side not in sides:
            continue
        dist = _handler_ball_dist(e)
        is_prog = label == "High Pass" or (dist is not None and dist >= long_thresh)
        if not is_prog:
            continue
        sides[side]["progressive_passes_attempted"] += 1
        if _possession_held(timeline, t, side):
            sides[side]["progressive_passes_completed"] += 1

    out: dict[str, Any] = {}
    for side, row in sides.items():
        att = int(row["progressive_passes_attempted"])
        comp = int(row["progressive_passes_completed"])
        out[side] = {
            "progressive_passes_attempted": att,
            "progressive_passes_completed": comp,
            "progressive_passes": comp,  # alias used by some board rows
        }
    out["match"] = {
        "progressive_passes_attempted": (
            out["home"]["progressive_passes_attempted"]
            + out["away"]["progressive_passes_attempted"]
        ),
        "progressive_passes_completed": (
            out["home"]["progressive_passes_completed"]
            + out["away"]["progressive_passes_completed"]
        ),
    }
    return out


def estimate_aerials(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    debounce: bool = True,
) -> dict[str, Any]:
    """Header tags → aerials total; possession hold ≈ aerial won."""
    events = debounce_film_events(film_events) if debounce else list(film_events)
    sides = {s: {"aerials_total": 0, "aerials_won": 0} for s in ("home", "away")}
    for e in events:
        if e.get("label") != "Header":
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t)
        if side not in sides:
            continue
        sides[side]["aerials_total"] += 1
        # Won if same team still has ball shortly after, or flipped *to* them.
        after = _team_at(timeline, t + 2.0)
        if after == side or _possession_held(timeline, t, side):
            sides[side]["aerials_won"] += 1
    out: dict[str, Any] = {s: dict(v) for s, v in sides.items()}
    out["match"] = {
        "aerials_total": out["home"]["aerials_total"] + out["away"]["aerials_total"],
        "aerials_won": out["home"]["aerials_won"] + out["away"]["aerials_won"],
    }
    return out


def estimate_interceptions(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    duration_sec: float,
    max_per_90: float = DEFAULT_MAX_INT_PER_90,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
) -> dict[str, Any]:
    """Quieter possession flips near Pass/Cross tags ≈ interceptions."""
    budget = max(6, int(round(max_per_90 * float(duration_sec) / 5400.0)))
    cands: list[dict[str, Any]] = []
    for t, frm, to in _possession_flips(timeline):
        nearby = [
            e
            for e in film_events
            if abs(float(e.get("time_sec") or 0.0) - t) <= 2.0
        ]
        if not nearby:
            continue
        mot = max(float(e.get("motion") or 0.0) for e in nearby)
        labels = {e.get("label") for e in nearby}
        if not (labels & {"Pass", "High Pass", "Cross"}):
            continue
        # Avoid double-counting loud duel flips (those feed tackles).
        if mot >= 18.0 or (labels & {"Drive", "Shot", "Player Successful Tackle"}):
            continue
        if mot < 6.0:
            continue
        cands.append(
            {
                "time_sec": t,
                "team": to,
                "from_team": frm,
                "motion": round(mot, 2),
                "score": round(min(mot / 16.0, 1.0), 3),
                "source": "pass_cut_flip",
            }
        )
    pool = sorted(cands, key=lambda e: (-float(e["score"]), float(e["time_sec"])))
    chosen: list[dict[str, Any]] = []
    for e in pool:
        if any(abs(e["time_sec"] - o["time_sec"]) < min_gap_sec for o in chosen):
            continue
        chosen.append(e)
        if len(chosen) >= budget:
            break
    counts = Counter(e["team"] for e in chosen)
    return {
        "method": "pass-cut-flip-topk-v1",
        "budget": budget,
        "selected": chosen,
        "totals": {
            "home": {"interceptions": int(counts.get("home", 0))},
            "away": {"interceptions": int(counts.get("away", 0))},
            "match": {"interceptions": len(chosen)},
        },
    }


def estimate_clearances(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    frame_h: float = DEFAULT_FRAME_H,
    duration_sec: float,
    max_per_90: float = DEFAULT_MAX_CLR_PER_90,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    debounce: bool = True,
) -> dict[str, Any]:
    """Out near a goal line by the team that had the ball ≈ clearance."""
    events = debounce_film_events(film_events) if debounce else list(film_events)
    budget = max(6, int(round(max_per_90 * float(duration_sec) / 5400.0)))
    cands: list[dict[str, Any]] = []
    for e in events:
        if e.get("label") != "Out" or not e.get("ball_xy"):
            continue
        t = float(e.get("time_sec") or 0.0)
        gd = _goal_dist(float(e["ball_xy"][1]), frame_h)
        if gd > 0.16 * frame_h:
            continue
        # Clearing team = who had the ball just before the Out.
        side = _team_at(timeline, t - 1.0) or _team_at(timeline, t)
        if side not in {"home", "away"}:
            continue
        cands.append(
            {
                "time_sec": t,
                "team": side,
                "goal_dist": round(gd, 1),
                "score": round(1.0 - min(gd / (0.16 * frame_h), 1.0), 3),
                "source": "out_near_goal",
            }
        )
    pool = sorted(cands, key=lambda e: (-float(e["score"]), float(e["time_sec"])))
    chosen: list[dict[str, Any]] = []
    for e in pool:
        if any(abs(e["time_sec"] - o["time_sec"]) < min_gap_sec for o in chosen):
            continue
        chosen.append(e)
        if len(chosen) >= budget:
            break
    counts = Counter(e["team"] for e in chosen)
    return {
        "method": "out-near-goal-topk-v1",
        "budget": budget,
        "selected": chosen,
        "totals": {
            "home": {"clearances": int(counts.get("home", 0))},
            "away": {"clearances": int(counts.get("away", 0))},
            "match": {"clearances": len(chosen)},
        },
    }


def build_secondary(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    duration_sec: float,
    frame_w: float = DEFAULT_FRAME_W,
    frame_h: float = DEFAULT_FRAME_H,
) -> dict[str, Any]:
    """Compute all Phase-8 secondary board fills."""
    _ = frame_w  # reserved for lateral filters later
    progressive = estimate_progressive_passes(
        film_events, timeline, frame_h=frame_h, debounce=True
    )
    aerials = estimate_aerials(film_events, timeline, debounce=True)
    interceptions = estimate_interceptions(
        film_events, timeline, duration_sec=duration_sec
    )
    clearances = estimate_clearances(
        film_events, timeline, frame_h=frame_h, duration_sec=duration_sec
    )
    sides: dict[str, Any] = {}
    for side in ("home", "away"):
        sides[side] = {
            **(progressive.get(side) or {}),
            **(aerials.get(side) or {}),
            "interceptions": (interceptions.get("totals") or {})
            .get(side, {})
            .get("interceptions", 0),
            "clearances": (clearances.get("totals") or {})
            .get(side, {})
            .get("clearances", 0),
        }
    return {
        "phase": PHASE,
        "method": "film-secondary-fill-v1",
        "progressive": progressive,
        "aerials": aerials,
        "interceptions": interceptions,
        "clearances": clearances,
        "totals": sides,
        "warning": (
            "Approximate progressive/aerials/interceptions/clearances from film "
            "+ possession. Not Opta. xG/PPDA still pending."
        ),
    }


def merge_secondary_into_sheet(
    sheet: dict[str, Any], secondary: dict[str, Any]
) -> dict[str, Any]:
    """Write Phase-8 fields onto the team board."""
    out = dict(sheet)
    totals = secondary.get("totals") or {}
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        block = totals.get(side) or {}
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        passes = dict(sections.get("passes") or {})
        defence = dict(sections.get("defence") or {})

        for key in (
            "progressive_passes_attempted",
            "progressive_passes_completed",
            "progressive_passes",
        ):
            if block.get(key) is not None:
                t[key] = int(block[key])
                if key != "progressive_passes":
                    passes[key] = int(block[key])
                else:
                    passes["progressive_passes_completed"] = int(
                        block.get("progressive_passes_completed", block[key])
                    )

        for key in ("aerials_won", "aerials_total", "interceptions", "clearances"):
            if block.get(key) is not None:
                t[key] = int(block[key])
                defence[key] = int(block[key])

        prov["progressive_passes"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "High Pass / long Pass-Cross with possession hold",
        }
        prov["aerials_won"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "Header tags + possession after header",
        }
        prov["interceptions"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "quiet possession flips near Pass/Cross tags",
        }
        prov["clearances"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "Out near goal line by prior possession team",
        }

        sections["passes"] = passes
        sections["defence"] = defence
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams
    out["secondary"] = {
        "phase": PHASE,
        "method": secondary.get("method"),
        "totals": totals,
        "progressive": secondary.get("progressive"),
        "aerials": secondary.get("aerials"),
        "interceptions": {
            "method": (secondary.get("interceptions") or {}).get("method"),
            "totals": (secondary.get("interceptions") or {}).get("totals"),
            "budget": (secondary.get("interceptions") or {}).get("budget"),
        },
        "clearances": {
            "method": (secondary.get("clearances") or {}).get("method"),
            "totals": (secondary.get("clearances") or {}).get("totals"),
            "budget": (secondary.get("clearances") or {}).get("budget"),
        },
        "warning": secondary.get("warning"),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    pending = [
        f
        for f in (cov.get("pending_later_phases") or [])
        if f
        not in {
            "progressive_passes",
            "aerials_won",
            "interceptions",
            "clearances",
        }
    ]
    approx = sorted(
        set(cov.get("approximate_video") or [])
        | {
            "progressive_passes",
            "aerials_won",
            "aerials_total",
            "interceptions",
            "clearances",
        }
    )
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    th, ta = totals.get("home") or {}, totals.get("away") or {}
    cov["phase8"] = {
        "prog_home": th.get("progressive_passes_completed"),
        "prog_away": ta.get("progressive_passes_completed"),
        "aerials_home": th.get("aerials_won"),
        "aerials_away": ta.get("aerials_won"),
        "ints_home": th.get("interceptions"),
        "ints_away": ta.get("interceptions"),
        "clr_home": th.get("clearances"),
        "clr_away": ta.get("clearances"),
        "method": secondary.get("method"),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = (
        "fact_plus_film_plus_tracking_plus_shots_plus_sot_plus_gk_plus_actions_plus_secondary"
    )
    note = (src.get("note") or "").rstrip()
    if "Phase 8:" not in note:
        src["note"] = (
            f"{note} Phase 8: approximate progressive/aerials/ints/clearances."
        ).strip()
    out["source"] = src
    return out


def _rebuild_sheet_through_phase7(pack_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-apply phases 3→7 when film + tracking exist."""
    meta, sheet = _rebuild_sheet_through_phase6(pack_id)
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    if events_path.exists() and tracking_path.exists():
        film_events = json.loads(events_path.read_text(encoding="utf-8"))
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
        timeline = tracking.get("timeline") or []
        duration = float(
            tracking.get("end_sec") or tracking.get("duration_sec") or 90 * 60
        )
        passes = estimate_pass_completion(film_events, timeline, debounce=True)
        scored = score_tackle_candidates(film_events, timeline)
        tackles = select_tackles(
            scored, film_events, timeline, duration_sec=max(duration, 60)
        )
        sheet = merge_actions_into_sheet(sheet, passes=passes, tackles=tackles)
        if (meta.get("phase7") or {}).get("status") == "done":
            src = dict(sheet.get("source") or {})
            src["phase"] = PHASE7
            sheet["source"] = src
    return meta, sheet


def run_phase8(pack_id: str, *, on_progress: ProgressCb | None = None) -> dict[str, Any]:
    """Fill secondary board stats and merge onto the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    if not events_path.exists():
        raise ValueError("Run Phase 2 film analyze first")
    if not tracking_path.exists():
        raise ValueError("Run Phase 3 tracking first")

    meta["phase8"] = {
        "status": "running",
        "progress": {"stage": "secondary_fill", "pct": 20},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "secondary_fill", "pct": 20})

    film_events = json.loads(events_path.read_text(encoding="utf-8"))
    tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
    timeline = tracking.get("timeline") or []
    duration = float(
        tracking.get("end_sec")
        or tracking.get("duration_sec")
        or (meta.get("video") or {}).get("duration_sec")
        or 90 * 60
    )
    if duration < 60:
        duration = 90 * 60
    fw, fh = _frame_size(meta, tracking)

    secondary = build_secondary(
        film_events, timeline, duration_sec=duration, frame_w=fw, frame_h=fh
    )
    secondary["created_at"] = time.time()

    if on_progress:
        on_progress({"stage": "merge_sheet", "pct": 75})

    meta, sheet = _rebuild_sheet_through_phase7(pack_id)
    sheet = merge_secondary_into_sheet(sheet, secondary)

    sec_path = store.pack_dir(pack_id) / "secondary.json"
    sec_path.write_text(json.dumps(secondary, indent=2, default=str), encoding="utf-8")
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")

    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["secondary_path"] = str(sec_path)
    meta["status"] = "phase8_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    meta["phase8"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "totals": secondary.get("totals"),
        "method": secondary.get("method"),
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
