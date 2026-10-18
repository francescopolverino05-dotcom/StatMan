"""Phase 7: fill pass completion + approximate tackles from film + possession.

Pass attempts already come from Phase 3 (debounced film tags). Completion is
inferred when possession stays with the passing team shortly after the tag.

Tackles: film ``Player Successful Tackle`` tags are almost empty on broadcast
YOLO. We add a rate-limited set of contested possession flips (high motion +
crowd near a home↔away change) as approximate successful tackles for the team
that won the ball.

Still approximate — not Opta. Goal is a filled board for later accuracy audit.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from statman.match_pack import store
from statman.match_pack.tracking import debounce_film_events

PHASE = "match-pack-phase7"
ProgressCb = Callable[[dict[str, Any]], None]

PASS_LABELS = {"Pass", "High Pass", "Cross", "Throw In", "Free Kick"}
DEFAULT_MAX_TACKLES_PER_90 = 18.0
DEFAULT_TACKLE_MIN_GAP_SEC = 30.0
DEFAULT_TACKLE_MIN_SCORE = 0.55


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


def estimate_pass_completion(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    debounce: bool = True,
) -> dict[str, Any]:
    """Attempt/complete/accuracy per side from pass-like tags + possession hold."""
    events = debounce_film_events(film_events) if debounce else list(film_events)
    sides = {
        "home": {"passes_attempted": 0, "passes_completed": 0},
        "away": {"passes_attempted": 0, "passes_completed": 0},
    }
    for e in events:
        if e.get("label") not in PASS_LABELS:
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t)
        if side not in sides:
            continue
        sides[side]["passes_attempted"] += 1
        later = [
            _team_at(timeline, t + dt)
            for dt in (1.5, 2.5, 3.5, 4.5)
        ]
        later = [x for x in later if x in {"home", "away"}]
        if later and sum(1 for x in later if x == side) >= (len(later) + 1) // 2:
            sides[side]["passes_completed"] += 1

    out: dict[str, Any] = {}
    for side, row in sides.items():
        att = int(row["passes_attempted"])
        comp = int(row["passes_completed"])
        acc = round(100.0 * float(comp) / float(att), 1) if att else None
        out[side] = {
            "passes_attempted": att,
            "passes_completed": comp,
            "pass_accuracy": acc,
        }
    out["match"] = {
        "passes_attempted": out["home"]["passes_attempted"] + out["away"]["passes_attempted"],
        "passes_completed": out["home"]["passes_completed"] + out["away"]["passes_completed"],
    }
    return out


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


def score_tackle_candidates(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score contested possession flips as approximate tackle wins."""
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
        people = max(int(e.get("people_count") or 0) for e in nearby)
        labels = {e.get("label") for e in nearby}
        contested = bool(
            labels
            & {"Drive", "Out", "Header", "Player Successful Tackle", "Shot"}
        )
        if mot < 12.0 or people < 10:
            continue
        if not contested and mot < 18.0:
            continue
        score = (
            0.4 * min(mot / 30.0, 1.0)
            + 0.3 * min(people / 22.0, 1.0)
            + 0.3 * (1.0 if contested else 0.3)
        )
        cands.append(
            {
                "time_sec": t,
                "minute": round(t / 60.0, 2),
                "team": to,
                "from_team": frm,
                "motion": round(mot, 2),
                "people_count": people,
                "score": round(float(score), 3),
                "labels": sorted(x for x in labels if x),
                "source": "possession_flip",
            }
        )
    return cands


def select_tackles(
    scored: list[dict[str, Any]],
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    duration_sec: float,
    max_tackles_per_90: float = DEFAULT_MAX_TACKLES_PER_90,
    min_gap_sec: float = DEFAULT_TACKLE_MIN_GAP_SEC,
    min_score: float = DEFAULT_TACKLE_MIN_SCORE,
) -> dict[str, Any]:
    """Rate-limit tackle candidates; always keep film Successful Tackle tags."""
    budget = max(8, int(round(max_tackles_per_90 * float(duration_sec) / 5400.0)))
    pool = sorted(
        [
            e
            for e in scored
            if float(e.get("score") or 0) >= min_score and e.get("team") in {"home", "away"}
        ],
        key=lambda e: (-float(e["score"]), float(e["time_sec"])),
    )
    chosen: list[dict[str, Any]] = []
    for e in pool:
        if any(abs(float(e["time_sec"]) - float(o["time_sec"])) < min_gap_sec for o in chosen):
            continue
        chosen.append(dict(e))
        if len(chosen) >= budget:
            break

    # Authoritative film tackle tags (rare) — force-include for the winning side.
    for e in film_events:
        if e.get("label") != "Player Successful Tackle":
            continue
        t = float(e.get("time_sec") or 0.0)
        side = _team_at(timeline, t) or "home"
        near_idx = [
            i
            for i, o in enumerate(chosen)
            if abs(t - float(o["time_sec"])) < min_gap_sec
        ]
        if near_idx:
            # Prefer overwriting the closest candidate with the film tag.
            i = min(near_idx, key=lambda j: abs(t - float(chosen[j]["time_sec"])))
            chosen[i] = {
                **chosen[i],
                "time_sec": t,
                "minute": round(t / 60.0, 2),
                "team": side,
                "score": 1.0,
                "motion": e.get("motion"),
                "people_count": e.get("people_count"),
                "source": "film_tackle",
                "film_backed": True,
            }
            continue
        chosen.append(
            {
                "time_sec": t,
                "minute": round(t / 60.0, 2),
                "team": side,
                "score": 1.0,
                "motion": e.get("motion"),
                "people_count": e.get("people_count"),
                "source": "film_tackle",
                "film_backed": True,
            }
        )

    chosen.sort(key=lambda e: float(e["time_sec"]))
    counts = Counter(e.get("team") for e in chosen if e.get("team") in {"home", "away"})
    return {
        "phase": PHASE,
        "method": "possession-flip-tackle-topk-v1",
        "budget": budget,
        "min_gap_sec": min_gap_sec,
        "min_score": min_score,
        "candidates_scored": len(scored),
        "selected": chosen,
        "totals": {
            "home": {"tackles": int(counts.get("home", 0))},
            "away": {"tackles": int(counts.get("away", 0))},
            "match": {"tackles": len(chosen)},
        },
        "warning": (
            "Approximate tackles from contested possession flips (+ rare film "
            "Successful Tackle tags). Not Opta duels."
        ),
    }


def merge_actions_into_sheet(
    sheet: dict[str, Any],
    *,
    passes: dict[str, Any],
    tackles: dict[str, Any],
) -> dict[str, Any]:
    """Write pass completion + rescored tackles onto the team board."""
    out = dict(sheet)
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        p = passes.get(side) or {}
        tk = (tackles.get("totals") or {}).get(side) or {}
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        passes_sec = dict(sections.get("passes") or {})
        defence = dict(sections.get("defence") or {})

        if p.get("passes_attempted") is not None:
            t["passes_attempted"] = int(p["passes_attempted"])
            passes_sec["passes_attempted"] = int(p["passes_attempted"])
        if p.get("passes_completed") is not None:
            t["passes_completed"] = int(p["passes_completed"])
            passes_sec["passes_completed"] = int(p["passes_completed"])
        if p.get("pass_accuracy") is not None:
            t["pass_accuracy"] = float(p["pass_accuracy"])
            passes_sec["pass_accuracy"] = float(p["pass_accuracy"])

        prov["passes_attempted"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "debounced film Pass/High Pass/Cross/Throw-in tags",
        }
        prov["passes_completed"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "possession held ~2–4s after pass tag",
        }
        prov["pass_accuracy"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "completed / attempted from possession hold",
        }

        if tk.get("tackles") is not None:
            t["tackles"] = int(tk["tackles"])
            defence["tackles"] = int(tk["tackles"])
            prov["tackles"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "contested possession flips (top-K) + film tackle tags",
            }

        sections["passes"] = passes_sec
        sections["defence"] = defence
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams

    out["actions"] = {
        "phase": PHASE,
        "passes": passes,
        "tackles": {
            "method": tackles.get("method"),
            "totals": tackles.get("totals"),
            "budget": tackles.get("budget"),
            "selected": tackles.get("selected") or [],
            "warning": tackles.get("warning"),
        },
        "warning": (
            "Approximate pass completion (possession hold) and tackles "
            "(contested flips). Not Opta."
        ),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    pending = [
        f
        for f in (cov.get("pending_later_phases") or [])
        if f not in {"pass_accuracy", "tackles"}
    ]
    approx = sorted(
        set(cov.get("approximate_video") or [])
        | {
            "passes_attempted",
            "passes_completed",
            "pass_accuracy",
            "tackles",
        }
    )
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    cov["phase7"] = {
        "passes_home": (passes.get("home") or {}).get("passes_attempted"),
        "passes_away": (passes.get("away") or {}).get("passes_attempted"),
        "pass_acc_home": (passes.get("home") or {}).get("pass_accuracy"),
        "pass_acc_away": (passes.get("away") or {}).get("pass_accuracy"),
        "tackles_home": (tackles.get("totals") or {}).get("home", {}).get("tackles"),
        "tackles_away": (tackles.get("totals") or {}).get("away", {}).get("tackles"),
        "method_passes": "possession-hold-v1",
        "method_tackles": tackles.get("method"),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film_plus_tracking_plus_shots_plus_sot_plus_gk_plus_actions"
    note = (src.get("note") or "").rstrip()
    if "Phase 7:" not in note:
        src["note"] = (
            f"{note} Phase 7: approximate pass completion + tackle rescore."
        ).strip()
    out["source"] = src
    return out


def _rebuild_sheet_through_phase6(pack_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (meta, sheet) with phases 3→5→6 re-applied when artifacts exist."""
    from statman.match_pack.gk import build_gk_totals, merge_gk_into_sheet
    from statman.match_pack.phase3 import apply_phase3_to_sheet
    from statman.match_pack.sot import PHASE as PHASE5, merge_sot_into_sheet

    meta = apply_phase3_to_sheet(pack_id)
    sheet = meta.get("sheet") or {}
    shots_path = store.pack_dir(pack_id) / "shots.json"
    if shots_path.exists():
        shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
        if shot_result.get("phase") == PHASE5 or (meta.get("phase5") or {}).get(
            "status"
        ) == "done":
            sheet = merge_sot_into_sheet(sheet, shot_result)
            if (meta.get("phase6") or {}).get("status") == "done" or (
                store.pack_dir(pack_id) / "goalkeeper.json"
            ).exists():
                gk_totals = build_gk_totals(shot_result.get("totals") or {}, sheet)
                sheet = merge_gk_into_sheet(sheet, gk_totals)
    return meta, sheet


def run_phase7(
    pack_id: str,
    *,
    max_tackles_per_90: float = DEFAULT_MAX_TACKLES_PER_90,
    min_gap_sec: float = DEFAULT_TACKLE_MIN_GAP_SEC,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Fill pass completion + tackles and merge onto the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    if not events_path.exists():
        raise ValueError("Run Phase 2 film analyze first")
    if not tracking_path.exists():
        raise ValueError("Run Phase 3 tracking first")

    meta["phase7"] = {
        "status": "running",
        "progress": {"stage": "pass_completion", "pct": 15},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "pass_completion", "pct": 15})

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

    passes = estimate_pass_completion(film_events, timeline, debounce=True)
    if on_progress:
        on_progress({"stage": "tackle_rescore", "pct": 55})
    scored = score_tackle_candidates(film_events, timeline)
    tackles = select_tackles(
        scored,
        film_events,
        timeline,
        duration_sec=duration,
        max_tackles_per_90=max_tackles_per_90,
        min_gap_sec=min_gap_sec,
    )

    meta, sheet = _rebuild_sheet_through_phase6(pack_id)
    sheet = merge_actions_into_sheet(sheet, passes=passes, tackles=tackles)

    actions_path = store.pack_dir(pack_id) / "actions.json"
    payload = {
        "phase": PHASE,
        "passes": passes,
        "tackles": tackles,
        "created_at": time.time(),
        "warning": (
            "Approximate pass completion + tackles for board fill / later audit."
        ),
    }
    actions_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["actions_path"] = str(actions_path)
    meta["status"] = "phase7_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    meta["phase7"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "passes": passes,
        "tackles": tackles.get("totals"),
        "tackle_selected": len(tackles.get("selected") or []),
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
