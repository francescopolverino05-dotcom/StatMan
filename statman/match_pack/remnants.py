"""Phase 10: fill remaining catalog blanks from film + shots + possession.

Phases 1–9 leave several World Cup–style board rows as ``—`` (throw-ins,
crosses, recoveries, shot splits, etc.). This module adds approximate
team-split fills so the catalog is denser for the accuracy audit.

Still approximate — not Opta. Prefer facts when already present.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from typing import Any, Callable

import numpy as np

from statman.match_pack import store
from statman.match_pack.tracking import debounce_film_events

PHASE = "match-pack-phase10"
ProgressCb = Callable[[dict[str, Any]], None]

DEFAULT_FRAME_W = 1280.0
DEFAULT_FRAME_H = 720.0
# Broadcast: nearer a goal line ≈ inside-box-ish (pixels from edge).
INSIDE_BOX_GD_MAX = 140.0
# High recovery: flip won in opponent half (ball near their goal line).
HIGH_RECOVERY_GD_MAX = 0.40  # fraction of frame height from opponent goal edge


def _team_at(
    timeline: list[dict[str, Any]], t: float, *, max_dt: float = 8.0
) -> str | None:
    if not timeline:
        return None
    times = np.array([row["time_sec"] for row in timeline], dtype=np.float64)
    i = int(np.argmin(np.abs(times - t)))
    if abs(float(times[i]) - t) > max_dt:
        return None
    side = timeline[i].get("team")
    return side if side in {"home", "away"} else None


def _possession_flips(timeline: list[dict[str, Any]]) -> list[tuple[float, str, str]]:
    flips: list[tuple[float, str, str]] = []
    prev_t: float | None = None
    prev_side: str | None = None
    for row in timeline:
        side = row.get("team")
        t = float(row.get("time_sec") or 0.0)
        if side not in {"home", "away"}:
            continue
        if prev_side in {"home", "away"} and side != prev_side and prev_t is not None:
            flips.append(((prev_t + t) / 2.0, prev_side, side))
        prev_side = side
        prev_t = t
    return flips


def _ball_y_near(t: float, film_events: list[dict[str, Any]]) -> float | None:
    near = [
        e
        for e in film_events
        if e.get("ball_xy") and abs(float(e.get("time_sec") or 0.0) - t) <= 2.5
    ]
    if not near:
        return None
    near.sort(key=lambda e: abs(float(e.get("time_sec") or 0.0) - t))
    return float(near[0]["ball_xy"][1])


def _hold_complete(
    timeline: list[dict[str, Any]], t: float, side: str
) -> bool:
    later = [_team_at(timeline, t + dt) for dt in (1.5, 2.5, 3.5)]
    later = [x for x in later if x in {"home", "away"}]
    if not later:
        return False
    return sum(1 for x in later if x == side) >= (len(later) + 1) // 2


def estimate_label_split(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    labels: set[str],
    debounce: bool = True,
) -> dict[str, int]:
    events = debounce_film_events(film_events) if debounce else list(film_events)
    counts = Counter()
    for e in events:
        if e.get("label") not in labels:
            continue
        side = _team_at(timeline, float(e.get("time_sec") or 0.0))
        if side in {"home", "away"}:
            counts[side] += 1
    return {"home": int(counts["home"]), "away": int(counts["away"])}


def estimate_crosses(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    debounce: bool = True,
) -> dict[str, dict[str, int]]:
    events = debounce_film_events(film_events) if debounce else list(film_events)
    out = {
        "home": {"crosses_total": 0, "crosses_completed": 0},
        "away": {"crosses_total": 0, "crosses_completed": 0},
    }
    for e in events:
        if e.get("label") != "Cross":
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t)
        if side not in out:
            continue
        out[side]["crosses_total"] += 1
        if _hold_complete(timeline, t, side):
            out[side]["crosses_completed"] += 1
    return out


def estimate_long_balls(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    debounce: bool = True,
) -> dict[str, dict[str, int]]:
    events = debounce_film_events(film_events) if debounce else list(film_events)
    out = {
        "home": {"long_balls_total": 0, "long_balls_completed": 0},
        "away": {"long_balls_total": 0, "long_balls_completed": 0},
    }
    for e in events:
        if e.get("label") != "High Pass":
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t)
        if side not in out:
            continue
        out[side]["long_balls_total"] += 1
        if _hold_complete(timeline, t, side):
            out[side]["long_balls_completed"] += 1
    return out


def estimate_recoveries(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    frame_h: float = DEFAULT_FRAME_H,
) -> dict[str, dict[str, int]]:
    """Every possession flip ≈ recovery for the winner; high = near opp goal."""
    out = {
        "home": {"recoveries": 0, "high_recoveries": 0, "balls_lost": 0},
        "away": {"recoveries": 0, "high_recoveries": 0, "balls_lost": 0},
    }
    for t, frm, to in _possession_flips(timeline):
        out[to]["recoveries"] += 1
        out[frm]["balls_lost"] += 1
        y = _ball_y_near(t, film_events)
        if y is None:
            continue
        # Winner recovered high if ball is near the *loser's* goal line.
        # Heuristic: home attacks top (y→0), away attacks bottom (y→h).
        if to == "home" and y <= HIGH_RECOVERY_GD_MAX * frame_h:
            out[to]["high_recoveries"] += 1
        elif to == "away" and y >= frame_h * (1.0 - HIGH_RECOVERY_GD_MAX):
            out[to]["high_recoveries"] += 1
    return out


def estimate_ground_duels(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Contested Drive-near flips as ground duels; winner gets the win."""
    out = {
        "home": {"ground_duels_won": 0, "ground_duels_total": 0},
        "away": {"ground_duels_won": 0, "ground_duels_total": 0},
    }
    for t, frm, to in _possession_flips(timeline):
        nearby = [
            e
            for e in film_events
            if abs(float(e.get("time_sec") or 0.0) - t) <= 2.0
        ]
        labels = {e.get("label") for e in nearby}
        if not (labels & {"Drive", "Player Successful Tackle", "Header"}):
            continue
        out[to]["ground_duels_won"] += 1
        out[to]["ground_duels_total"] += 1
        out[frm]["ground_duels_total"] += 1
    return out


def estimate_shot_splits(
    selected_shots: list[dict[str, Any]],
    film_events: list[dict[str, Any]],
    *,
    frame_h: float = DEFAULT_FRAME_H,
) -> dict[str, dict[str, int | float | None]]:
    """Derive attack rows that stay blank after Phase 5/9."""
    sides: dict[str, dict[str, Any]] = {
        "home": {
            "shots": 0,
            "shots_on_target": 0,
            "blocked_shots": 0,
            "missed_shots": 0,
            "shots_inside_box": 0,
            "shots_outside_box": 0,
            "headed_shots": 0,
            "shot_accuracy": None,
            "key_passes": 0,
        },
        "away": {
            "shots": 0,
            "shots_on_target": 0,
            "blocked_shots": 0,
            "missed_shots": 0,
            "shots_inside_box": 0,
            "shots_outside_box": 0,
            "headed_shots": 0,
            "shot_accuracy": None,
            "key_passes": 0,
        },
    }
    for shot in selected_shots:
        side = shot.get("team")
        if side not in sides:
            continue
        sides[side]["shots"] += 1
        on = bool(shot.get("on_target"))
        if on:
            sides[side]["shots_on_target"] += 1
        gd = float(shot.get("goal_dist") if shot.get("goal_dist") is not None else 999.0)
        if gd <= INSIDE_BOX_GD_MAX:
            sides[side]["shots_inside_box"] += 1
        else:
            sides[side]["shots_outside_box"] += 1

        t = float(shot.get("time_sec") or 0.0)
        nearby = [
            e
            for e in film_events
            if abs(float(e.get("time_sec") or 0.0) - t) <= 4.0
        ]
        labels = {e.get("label") for e in nearby}
        if "Header" in labels:
            sides[side]["headed_shots"] += 1
        # Blocked: not on target + Out shortly after near the shot.
        if not on and any(
            e.get("label") == "Out"
            and float(e.get("time_sec") or 0.0) >= t - 0.2
            for e in nearby
        ):
            sides[side]["blocked_shots"] += 1
        # Key pass: Cross/Pass in the few seconds before the shot (assist-ish).
        pre = [
            e
            for e in film_events
            if e.get("label") in {"Pass", "Cross", "High Pass"}
            and 0.2 <= (t - float(e.get("time_sec") or 0.0)) <= 6.0
        ]
        if pre:
            sides[side]["key_passes"] += 1

        _ = frame_h  # reserved for tighter box geometry later

    for side, row in sides.items():
        shots = int(row["shots"])
        sot = int(row["shots_on_target"])
        blocked = int(row["blocked_shots"])
        row["missed_shots"] = max(0, shots - sot - blocked)
        row["shot_accuracy"] = (
            round(100.0 * float(sot) / float(shots), 1) if shots else None
        )
    return sides


def build_remnants(
    *,
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    selected_shots: list[dict[str, Any]],
    frame_h: float = DEFAULT_FRAME_H,
) -> dict[str, Any]:
    throw_ins = estimate_label_split(film_events, timeline, labels={"Throw In"})
    free_kicks = estimate_label_split(film_events, timeline, labels={"Free Kick"})
    # Goal kicks: Out tags by the team that *gains* possession after a near-goal Out.
    # Simpler proxy: Out near a goal line attributed to the defending team at that time.
    goal_kicks = {"home": 0, "away": 0}
    for e in debounce_film_events(film_events):
        if e.get("label") != "Out" or not e.get("ball_xy"):
            continue
        by = float(e["ball_xy"][1])
        if min(by, frame_h - by) > 24.0:
            continue
        side = _team_at(timeline, float(e.get("time_sec") or 0.0))
        if side in goal_kicks:
            goal_kicks[side] += 1

    crosses = estimate_crosses(film_events, timeline)
    long_balls = estimate_long_balls(film_events, timeline)
    recoveries = estimate_recoveries(film_events, timeline, frame_h=frame_h)
    duels = estimate_ground_duels(film_events, timeline)
    shot_splits = estimate_shot_splits(
        selected_shots, film_events, frame_h=frame_h
    )
    # Blocks: film "Ball Player Block" if present, else blocked_shots from above.
    block_tags = estimate_label_split(
        film_events, timeline, labels={"Ball Player Block"}
    )

    sides: dict[str, Any] = {}
    for side in ("home", "away"):
        ss = shot_splits[side]
        blocks = int(block_tags.get(side) or 0) or int(ss.get("blocked_shots") or 0)
        sides[side] = {
            "throw_ins": int(throw_ins.get(side) or 0),
            "free_kicks": int(free_kicks.get(side) or 0),
            "goal_kicks": int(goal_kicks.get(side) or 0),
            **crosses[side],
            **long_balls[side],
            **recoveries[side],
            **duels[side],
            "blocks": blocks,
            "blocked_shots": int(ss.get("blocked_shots") or 0),
            "missed_shots": int(ss.get("missed_shots") or 0),
            "shots_inside_box": int(ss.get("shots_inside_box") or 0),
            "shots_outside_box": int(ss.get("shots_outside_box") or 0),
            "headed_shots": int(ss.get("headed_shots") or 0),
            "shot_accuracy": ss.get("shot_accuracy"),
            "key_passes": int(ss.get("key_passes") or 0),
        }

    return {
        "phase": PHASE,
        "method": "film-remnant-fill-v1",
        "totals": sides,
        "warning": (
            "Approximate remnant board fills (throw-ins, crosses, recoveries, "
            "shot splits, etc.) from film + possession + Phase-4/5 shots. Not Opta. "
            "Fouls stay fact/missing — broadcast YOLO has no reliable foul label."
        ),
    }


def merge_remnants_into_sheet(
    sheet: dict[str, Any], remnants: dict[str, Any]
) -> dict[str, Any]:
    """Write Phase-10 fields; do not overwrite fact totals already set."""
    out = dict(sheet)
    totals = remnants.get("totals") or {}
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        block = totals.get(side) or {}
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        match = dict(sections.get("match") or {})
        attack = dict(sections.get("attack") or {})
        passes = dict(sections.get("passes") or {})
        defence = dict(sections.get("defence") or {})

        def _fill(key: str, section: dict[str, Any], *, only_if_empty: bool = True) -> None:
            val = block.get(key)
            if val is None:
                return
            if only_if_empty and t.get(key) is not None:
                return
            t[key] = val
            section[key] = val

        for key in ("throw_ins", "free_kicks", "goal_kicks"):
            _fill(key, match, only_if_empty=True)
            if t.get(key) is not None:
                prov[key] = {
                    "status": "approximate_video" if block.get(key) is not None else "fact",
                    "phase": PHASE,
                    "detail": "film tag split by possession (facts win when present)",
                }

        for key in (
            "blocked_shots",
            "missed_shots",
            "shots_inside_box",
            "shots_outside_box",
            "headed_shots",
            "key_passes",
            "shot_accuracy",
        ):
            _fill(key, attack, only_if_empty=False if key == "shot_accuracy" else True)
            if key != "shot_accuracy" or t.get("shot_accuracy") is not None:
                prov.setdefault(
                    key,
                    {
                        "status": "approximate_video",
                        "phase": PHASE,
                        "detail": "derived from Phase-4/5 selected shots + film context",
                    },
                )

        for key in (
            "crosses_total",
            "crosses_completed",
            "long_balls_total",
            "long_balls_completed",
        ):
            _fill(key, passes, only_if_empty=True)
            prov[key] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "Cross / High Pass tags + possession hold",
            }

        for key in (
            "recoveries",
            "high_recoveries",
            "balls_lost",
            "blocks",
            "ground_duels_won",
            "ground_duels_total",
        ):
            _fill(key, defence, only_if_empty=True)
            prov[key] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "possession flips / film tags (approximate)",
            }

        # Fouls intentionally left pending — no reliable film cue yet.
        sections["match"] = match
        sections["attack"] = attack
        sections["passes"] = passes
        sections["defence"] = defence
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams
    out["remnants"] = {
        "phase": PHASE,
        "method": remnants.get("method"),
        "totals": totals,
        "warning": remnants.get("warning"),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    filled = {
        "throw_ins",
        "free_kicks",
        "goal_kicks",
        "shot_accuracy",
        "recoveries",
        "blocks",
    }
    pending = [f for f in (cov.get("pending_later_phases") or []) if f not in filled]
    # Keep fouls in pending explicitly.
    if "fouls_committed" not in pending:
        pending.append("fouls_committed")
    approx = sorted(
        set(cov.get("approximate_video") or [])
        | {
            "throw_ins",
            "crosses",
            "long_balls",
            "recoveries",
            "blocks",
            "shot_splits",
            "ground_duels",
        }
    )
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    th, ta = totals.get("home") or {}, totals.get("away") or {}
    cov["phase10"] = {
        "throw_ins_home": th.get("throw_ins"),
        "throw_ins_away": ta.get("throw_ins"),
        "recoveries_home": th.get("recoveries"),
        "recoveries_away": ta.get("recoveries"),
        "crosses_home": th.get("crosses_total"),
        "crosses_away": ta.get("crosses_total"),
        "method": remnants.get("method"),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "match_pack_board_filled_approximate"
    note = (src.get("note") or "").rstrip()
    if "Phase 10:" not in note:
        src["note"] = (
            f"{note} Phase 10: remnant catalog fills (throw-ins/crosses/recoveries/"
            "shot splits). Fouls still pending."
        ).strip()
    out["source"] = src
    return out


def run_phase10(pack_id: str, *, on_progress: ProgressCb | None = None) -> dict[str, Any]:
    """Fill remnant catalog fields on an existing Phase-9 board."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    shots_path = store.pack_dir(pack_id) / "shots.json"
    if not events_path.exists():
        raise ValueError("Run film analyze first")
    if not tracking_path.exists():
        raise ValueError("Run Phase 3 tracking first")

    meta["phase10"] = {
        "status": "running",
        "progress": {"stage": "remnant_fill", "pct": 15},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "remnant_fill", "pct": 15})

    film_events = json.loads(events_path.read_text(encoding="utf-8"))
    tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
    timeline = tracking.get("timeline") or []
    selected: list[dict[str, Any]] = []
    if shots_path.exists():
        shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
        selected = list(shot_result.get("selected") or [])
    fh = float(
        tracking.get("frame_h")
        or tracking.get("height")
        or (meta.get("video") or {}).get("height")
        or DEFAULT_FRAME_H
    )

    remnants = build_remnants(
        film_events=film_events,
        timeline=timeline,
        selected_shots=selected,
        frame_h=fh,
    )
    remnants["created_at"] = time.time()

    if on_progress:
        on_progress({"stage": "merge_sheet", "pct": 70})

    # Rebuild through phase 9 when possible so re-runs stay consistent.
    from statman.match_pack.xg_ppda import run_phase9

    # Prefer merging onto current sheet after ensuring phase9 fields exist.
    sheet = meta.get("sheet") or {}
    if (meta.get("phase9") or {}).get("status") != "done" and shots_path.exists():
        try:
            meta = run_phase9(pack_id)
            sheet = meta.get("sheet") or sheet
        except Exception:  # noqa: BLE001 — still merge remnants onto whatever we have
            pass
    else:
        # Refresh phase9 merge chain lightly: read sheet.json if present.
        sheet_path = store.pack_dir(pack_id) / "sheet.json"
        if sheet_path.exists():
            sheet = json.loads(sheet_path.read_text(encoding="utf-8"))

    sheet = merge_remnants_into_sheet(sheet, remnants)
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    remnants_path = store.pack_dir(pack_id) / "remnants.json"
    remnants_path.write_text(
        json.dumps(remnants, indent=2, default=str), encoding="utf-8"
    )

    meta = store.read_meta(pack_id) or meta
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["remnants_path"] = str(remnants_path)
    meta["status"] = "phase10_ready"
    meta["phase"] = PHASE
    meta["coverage"] = (sheet.get("source") or {}).get("coverage")
    meta["phase10"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "totals": remnants.get("totals"),
        "method": remnants.get("method"),
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
