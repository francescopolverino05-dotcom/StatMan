"""Phase 6: goalkeeper sheet from opponent SoT + fact goals conceded.

After Phase 5 we trust approximate SoT enough to derive:

- shots faced / shots on target faced = opponent SoT
- goals conceded = fact (already on the sheet)
- saves = max(0, SoT faced − goals conceded)
- save % = saves / SoT faced × 100

Still approximate — not Opta. Does not invent shot-stopping from video.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from statman.match_pack import store
from statman.match_pack.sot import PHASE as PHASE5, merge_sot_into_sheet

PHASE = "match-pack-phase6"
ProgressCb = Callable[[dict[str, Any]], None]


def gk_from_sot(
    *,
    opponent_sot: int,
    goals_conceded: int,
) -> dict[str, Any]:
    """Derive GK counting stats from opponent SoT and fact goals conceded."""
    faced = max(0, int(opponent_sot))
    conceded = max(0, int(goals_conceded))
    # A goal always came from an on-target shot; never report negative saves.
    if conceded > faced:
        faced = conceded
    saves = max(0, faced - conceded)
    save_pct = round(100.0 * float(saves) / float(faced), 1) if faced > 0 else None
    return {
        "shots_faced": faced,
        "shots_on_target_faced": faced,
        "goals_conceded": conceded,
        "saves": saves,
        "gk_saves": saves,
        "save_pct": save_pct,
    }


def build_gk_totals(shot_totals: dict[str, Any], sheet: dict[str, Any]) -> dict[str, Any]:
    """Build home/away GK blocks from Phase-5 shot totals + sheet goals conceded."""
    teams = sheet.get("teams") or []
    out: dict[str, Any] = {"home": {}, "away": {}, "match": {}}
    for idx, side in enumerate(("home", "away")):
        other = "away" if side == "home" else "home"
        opp_sot = int(((shot_totals.get(other) or {}).get("shots_on_target")) or 0)
        conceded = 0
        if idx < len(teams):
            conceded = int(teams[idx].get("goals_conceded") or 0)
            gk_sec = (teams[idx].get("sections") or {}).get("goalkeeper") or {}
            if gk_sec.get("goals_conceded") is not None:
                conceded = int(gk_sec["goals_conceded"])
        block = gk_from_sot(opponent_sot=opp_sot, goals_conceded=conceded)
        block["opponent_sot"] = opp_sot
        out[side] = block
    out["match"] = {
        "shots_faced": out["home"]["shots_faced"] + out["away"]["shots_faced"],
        "saves": out["home"]["saves"] + out["away"]["saves"],
        "goals_conceded": out["home"]["goals_conceded"] + out["away"]["goals_conceded"],
    }
    return out


def merge_gk_into_sheet(sheet: dict[str, Any], gk_totals: dict[str, Any]) -> dict[str, Any]:
    """Write Phase-6 GK fields onto the team board."""
    out = dict(sheet)
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        block = gk_totals.get(side) or {}
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        gk = dict(sections.get("goalkeeper") or {})

        for key in (
            "shots_faced",
            "shots_on_target_faced",
            "saves",
            "gk_saves",
            "save_pct",
        ):
            if key in block and block[key] is not None:
                t[key] = block[key]
                gk[key] = block[key]

        # Keep fact goals_conceded; refresh section copy.
        conceded = block.get("goals_conceded", t.get("goals_conceded"))
        if conceded is not None:
            t["goals_conceded"] = int(conceded)
            gk["goals_conceded"] = int(conceded)

        sections["goalkeeper"] = gk
        t["sections"] = sections
        prov["shots_faced"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "opponent Phase-5 SoT",
        }
        prov["shots_on_target_faced"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "opponent Phase-5 SoT",
        }
        prov["saves"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "SoT faced − fact goals conceded",
        }
        prov["save_pct"] = {
            "status": "approximate_video",
            "phase": PHASE,
            "detail": "saves / SoT faced",
        }
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams
    out["goalkeeper"] = {
        "phase": PHASE,
        "method": "sot-minus-goals-v1",
        "totals": gk_totals,
        "warning": (
            "Approximate GK sheet: shots faced = opponent SoT (Phase 5); "
            "saves = faced − fact goals conceded. Not Opta."
        ),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    approx = sorted(
        set(cov.get("approximate_video") or [])
        | {"shots_faced", "shots_on_target_faced", "saves", "save_pct"}
    )
    cov["approximate_video"] = approx
    cov["phase6"] = {
        "saves_home": (gk_totals.get("home") or {}).get("saves"),
        "saves_away": (gk_totals.get("away") or {}).get("saves"),
        "faced_home": (gk_totals.get("home") or {}).get("shots_faced"),
        "faced_away": (gk_totals.get("away") or {}).get("shots_faced"),
        "save_pct_home": (gk_totals.get("home") or {}).get("save_pct"),
        "save_pct_away": (gk_totals.get("away") or {}).get("save_pct"),
        "method": "sot-minus-goals-v1",
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film_plus_tracking_plus_shots_plus_sot_plus_gk"
    note = (src.get("note") or "").rstrip()
    if "Phase 6:" not in note:
        src["note"] = (
            f"{note} Phase 6: approximate GK (shots faced / saves from SoT)."
        ).strip()
    out["source"] = src
    return out


def run_phase6(pack_id: str, *, on_progress: ProgressCb | None = None) -> dict[str, Any]:
    """Fill GK board from Phase-5 SoT + fact goals conceded."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    shots_path = store.pack_dir(pack_id) / "shots.json"
    if not shots_path.exists():
        raise ValueError("Run Phase 4–5 (shots + SoT) first")

    meta["phase6"] = {
        "status": "running",
        "progress": {"stage": "gk_from_sot", "pct": 20},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "gk_from_sot", "pct": 20})

    shot_result = json.loads(shots_path.read_text(encoding="utf-8"))
    # Prefer Phase-5 labelled shots; if Phase 5 never ran, SoT may be goals-only.
    if shot_result.get("phase") != PHASE5 and (meta.get("phase5") or {}).get(
        "status"
    ) != "done":
        raise ValueError("Run Phase 5 SoT first")

    from statman.match_pack.phase3 import apply_phase3_to_sheet

    meta = apply_phase3_to_sheet(pack_id)
    # Re-apply Phase 5 SoT onto the Phase-3 base so the board stays consistent.
    sheet = merge_sot_into_sheet(meta.get("sheet") or {}, shot_result)
    gk_totals = build_gk_totals(shot_result.get("totals") or {}, sheet)
    sheet = merge_gk_into_sheet(sheet, gk_totals)

    gk_path = store.pack_dir(pack_id) / "goalkeeper.json"
    payload = {
        "phase": PHASE,
        "method": "sot-minus-goals-v1",
        "totals": gk_totals,
        "created_at": time.time(),
        "warning": (
            "Approximate GK sheet from opponent SoT − fact goals conceded."
        ),
    }
    gk_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["goalkeeper_path"] = str(gk_path)
    meta["status"] = "phase6_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    meta["phase6"] = {
        "status": "done",
        "progress": {"stage": "done", "pct": 100},
        "totals": gk_totals,
        "method": "sot-minus-goals-v1",
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    if on_progress:
        on_progress({"stage": "done", "pct": 100})
    return meta
