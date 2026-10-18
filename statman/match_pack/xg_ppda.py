"""Phase 9: approximate xG from shot list + rough PPDA.

xG: simple distance / SoT / fact-goal heuristic on Phase 4–5 selected shots
(no trained model — board fill for later audit).

PPDA: opponent pass attempts ÷ (tackles + interceptions). Classic Opta PPDA
is opposition-half only; we lack a reliable half split, so this is match-wide
and approximate.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from statman.match_pack import store
from statman.match_pack.secondary import (
    PHASE as PHASE8,
    build_secondary,
    merge_secondary_into_sheet,
    _rebuild_sheet_through_phase7,
    _frame_size,
)

PHASE = "match-pack-phase9"
ProgressCb = Callable[[dict[str, Any]], None]
DEFAULT_FRAME_H = 720.0


def shot_xg(shot: dict[str, Any], *, frame_h: float = DEFAULT_FRAME_H) -> float:
    """Heuristic single-shot xG in [0.02, 0.95]."""
    if shot.get("fact_goal"):
        # Goals still get a high but not 1.0 pre-shot style value.
        gd = shot.get("goal_dist")
        if gd is None:
            return 0.78
        close = max(0.0, 1.0 - float(gd) / (0.28 * frame_h))
        return round(min(0.92, 0.55 + 0.35 * close), 3)

    gd = shot.get("goal_dist")
    if gd is None:
        base = 0.07
    else:
        # Closer to goal line → higher xG.
        base = 0.04 + 0.42 * max(0.0, 1.0 - float(gd) / (0.38 * frame_h))

    prox = float(shot.get("prox") or 0.0)
    toward = float(shot.get("toward_n") or 0.0)
    score = float(shot.get("score") or 0.0)
    base *= 0.65 + 0.25 * prox + 0.10 * toward
    if score > 0:
        base *= 0.85 + 0.15 * min(score, 1.0)
    if shot.get("on_target"):
        base *= 1.25

    return round(float(min(0.85, max(0.02, base))), 3)


def estimate_xg(
    selected_shots: list[dict[str, Any]],
    *,
    frame_h: float = DEFAULT_FRAME_H,
) -> dict[str, Any]:
    """Sum heuristic xG per team; annotate each shot with ``xg``."""
    rows: list[dict[str, Any]] = []
    totals = {"home": 0.0, "away": 0.0}
    for e in selected_shots:
        row = dict(e)
        xg = shot_xg(row, frame_h=frame_h)
        row["xg"] = xg
        side = row.get("team")
        if side in totals:
            totals[side] += xg
        rows.append(row)
    return {
        "method": "distance-sot-heuristic-v1",
        "selected": rows,
        "totals": {
            "home": {"xg": round(totals["home"], 3)},
            "away": {"xg": round(totals["away"], 3)},
            "match": {"xg": round(totals["home"] + totals["away"], 3)},
        },
    }


def estimate_ppda(sheet: dict[str, Any]) -> dict[str, Any]:
    """PPDA ≈ opponent passes_attempted / (tackles + interceptions)."""
    teams = sheet.get("teams") or []
    out: dict[str, Any] = {"home": {}, "away": {}, "match": {}}
    for idx, side in enumerate(("home", "away")):
        other = 1 - idx
        t = teams[idx] if idx < len(teams) else {}
        o = teams[other] if other < len(teams) else {}
        opp_passes = int(o.get("passes_attempted") or 0)
        tackles = int(t.get("tackles") or 0)
        ints = int(t.get("interceptions") or 0)
        denom = tackles + ints
        ppda = round(float(opp_passes) / float(denom), 2) if denom > 0 else None
        out[side] = {
            "ppda": ppda,
            "opponent_passes": opp_passes,
            "defensive_actions": denom,
            "tackles": tackles,
            "interceptions": ints,
        }
    return out


def merge_xg_ppda_into_sheet(
    sheet: dict[str, Any],
    *,
    xg: dict[str, Any],
    ppda: dict[str, Any],
) -> dict[str, Any]:
    """Write xG + PPDA onto the team board."""
    out = dict(sheet)
    xg_tot = xg.get("totals") or {}
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        xv = (xg_tot.get(side) or {}).get("xg")
        pv = (ppda.get(side) or {}).get("ppda")
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        attack = dict(sections.get("attack") or {})
        defence = dict(sections.get("defence") or {})

        if xv is not None:
            t["xg"] = float(xv)
            attack["xg"] = float(xv)
            prov["xg"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "heuristic from shot distance / SoT / fact goals",
            }
        if pv is not None:
            t["ppda"] = float(pv)
            defence["ppda"] = float(pv)
            prov["ppda"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "opponent passes ÷ (tackles + interceptions), match-wide",
            }

        sections["attack"] = attack
        sections["defence"] = defence
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams

    # Keep shot list xG annotations when present.
    shots_block = dict(out.get("shots") or {})
    if xg.get("selected"):
        shots_block["selected"] = xg["selected"]
        shots_block["xg_method"] = xg.get("method")
    out["shots"] = shots_block

    out["xg_ppda"] = {
        "phase": PHASE,
        "xg": xg_tot,
        "ppda": {
            "home": ppda.get("home"),
            "away": ppda.get("away"),
        },
        "method_xg": xg.get("method"),
        "method_ppda": "passes-over-tackles-ints-v1",
        "warning": (
            "Approximate xG (distance/SoT heuristic) and match-wide PPDA. Not Opta."
        ),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    pending = [
        f for f in (cov.get("pending_later_phases") or []) if f not in {"xg", "ppda"}
    ]
    approx = sorted(set(cov.get("approximate_video") or []) | {"xg", "ppda"})
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    cov["phase9"] = {
        "xg_home": (xg_tot.get("home") or {}).get("xg"),
        "xg_away": (xg_tot.get("away") or {}).get("xg"),
        "ppda_home": (ppda.get("home") or {}).get("ppda"),
        "ppda_away": (ppda.get("away") or {}).get("ppda"),
        "method_xg": xg.get("method"),
        "method_ppda": "passes-over-tackles-ints-v1",
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "match_pack_board_filled_approximate"
    note = (src.get("note") or "").rstrip()
    if "Phase 9:" not in note:
        src["note"] = f"{note} Phase 9: approximate xG + PPDA.".strip()
    out["source"] = src
    return out


def _rebuild_sheet_through_phase8(pack_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-apply through Phase 8 when artifacts exist."""
    meta, sheet = _rebuild_sheet_through_phase7(pack_id)
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    if events_path.exists() and tracking_path.exists():
        film_events = json.loads(events_path.read_text(encoding="utf-8"))
        tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
        timeline = tracking.get("timeline") or []
        duration = float(
            tracking.get("end_sec") or tracking.get("duration_sec") or 90 * 60
        )
        fw, fh = _frame_size(meta, tracking)
        secondary = build_secondary(
            film_events,
            timeline,
            duration_sec=max(duration, 60),
            frame_w=fw,
            frame_h=fh,
        )
        sheet = merge_secondary_into_sheet(sheet, secondary)
        if (meta.get("phase8") or {}).get("status") == "done":
            src = dict(sheet.get("source") or {})
            src["phase"] = PHASE8
            sheet["source"] = src
    # Re-apply shots/SoT onto sheet if present (phase3 rebuild may blank them).
    shots_path = store.pack_dir(pack_id) / "shots.json"
    if shots_path.exists():
        from statman.match_pack.sot import merge_sot_into_sheet
        from statman.match_pack.gk import build_gk_totals, merge_gk_into_sheet

        shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
        sheet = merge_sot_into_sheet(sheet, shot_result)
        if (meta.get("phase6") or {}).get("status") == "done" or (
            store.pack_dir(pack_id) / "goalkeeper.json"
        ).exists():
            gk = build_gk_totals(shot_result.get("totals") or {}, sheet)
            sheet = merge_gk_into_sheet(sheet, gk)
    return meta, sheet


def run_phase9(pack_id: str, *, on_progress: ProgressCb | None = None) -> dict[str, Any]:
    """Fill xG + PPDA and merge onto the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    shots_path = store.pack_dir(pack_id) / "shots.json"
    if not shots_path.exists():
        raise ValueError("Run Phase 4–5 (shots + SoT) first")

    meta["phase9"] = {
        "status": "running",
        "progress": {"stage": "xg_ppda", "pct": 25},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "xg_ppda", "pct": 25})

    shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    tracking = (
        json.loads(tracking_path.read_text(encoding="utf-8"))
        if tracking_path.exists()
        else {}
    )
    _, fh = _frame_size(meta, tracking)

    xg = estimate_xg(shot_result.get("selected") or [], frame_h=fh)
    # Persist xG onto shots.json for later audits.
    shot_result = dict(shot_result)
    shot_result["selected"] = xg["selected"]
    shot_result["xg"] = xg["totals"]
    shot_result["xg_method"] = xg["method"]
    shots_path.write_text(json.dumps(shot_result, indent=2, default=str), encoding="utf-8")

    if on_progress:
        on_progress({"stage": "merge_sheet", "pct": 70})

    meta, sheet = _rebuild_sheet_through_phase8(pack_id)
    # Ensure shot totals/SoT still on board after rebuild.
    from statman.match_pack.sot import merge_sot_into_sheet

    sheet = merge_sot_into_sheet(sheet, shot_result)
    if (meta.get("phase6") or {}).get("status") == "done" or (
        store.pack_dir(pack_id) / "goalkeeper.json"
    ).exists():
        from statman.match_pack.gk import build_gk_totals, merge_gk_into_sheet

        sheet = merge_gk_into_sheet(
            sheet, build_gk_totals(shot_result.get("totals") or {}, sheet)
        )

    ppda = estimate_ppda(sheet)
    sheet = merge_xg_ppda_into_sheet(sheet, xg=xg, ppda=ppda)

    out_path = store.pack_dir(pack_id) / "xg_ppda.json"
    payload = {
        "phase": PHASE,
        "xg": xg,
        "ppda": ppda,
        "created_at": time.time(),
        "warning": (
            "Approximate xG + match-wide PPDA for board fill / later audit."
        ),
    }
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["xg_ppda_path"] = str(out_path)
    meta["status"] = "phase9_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    meta["phase9"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "xg": xg.get("totals"),
        "ppda": {
            "home": (ppda.get("home") or {}).get("ppda"),
            "away": (ppda.get("away") or {}).get("ppda"),
        },
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
