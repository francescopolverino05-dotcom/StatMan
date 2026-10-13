"""Phase 2: merge approximate film tags onto a fact-sourced match sheet.

Facts stay authoritative for goals, cards, substitutions, lineups, and formations.
Video spotting is attached under ``sheet["film"]`` (match-level, no team split).
"""

from __future__ import annotations

from typing import Any

PHASE = "match-pack-phase2"


def merge_film_into_sheet(
    sheet: dict[str, Any],
    film_stats: dict[str, Any],
    *,
    pack_id: str,
) -> dict[str, Any]:
    """Attach Phase-2 film tags. Does not invent a home/away split."""
    out = dict(sheet)
    totals = (film_stats or {}).get("totals") or {}
    label_counts = (film_stats or {}).get("label_counts") or {}
    source_film = (film_stats or {}).get("source") or {}

    film_block = {
        "phase": PHASE,
        "quality": "approximate",
        "method": source_film.get("method") or "yolo-person-ball-spotter-v1",
        "detector": source_film.get("detector"),
        "job_id": source_film.get("job_id"),
        "warning": (
            "Film tags are approximate broadcast spotting — not Opta/StatsBomb. "
            "Goals/cards/score stay fact-sourced. Shot/pass counts are over-sensitive "
            "and have no team split yet (Phase 3+ tracking)."
        ),
        "totals": {
            "events": totals.get("events"),
            "shots": totals.get("shots"),
            "passes": totals.get("passes"),
            "crosses": totals.get("crosses"),
            "high_passes": totals.get("high_passes"),
            "drives": totals.get("drives"),
            "headers": totals.get("headers"),
            "tackles": totals.get("tackles"),
            "blocks": totals.get("blocks"),
            "throw_ins": totals.get("throw_ins"),
            "free_kicks": totals.get("free_kicks"),
            "outs": totals.get("outs"),
            "goal_tags": totals.get("goals"),
        },
        "label_counts": label_counts,
        "per_90": (film_stats or {}).get("per_90") or {},
        "match": (film_stats or {}).get("match") or {},
    }
    out["film"] = film_block

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    approx = [
        "film_shots",
        "film_passes",
        "film_tackles",
        "film_headers",
        "film_drives",
        "film_crosses",
        "film_throw_ins",
        "film_events",
    ]
    pending = list(cov.get("pending_later_phases") or [])
    # Shots/passes/tackles remain pending on the *team* board until team split exists.
    cov["approximate_video"] = approx
    cov["pending_later_phases"] = pending
    cov["film_event_counts"] = {
        "events": totals.get("events"),
        "shots": totals.get("shots"),
        "passes": totals.get("passes"),
        "tackles": totals.get("tackles"),
        "headers": totals.get("headers"),
        "drives": totals.get("drives"),
        "crosses": totals.get("crosses"),
        "throw_ins": totals.get("throw_ins"),
        "free_kicks": totals.get("free_kicks"),
        "goal_tags": totals.get("goals"),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film"
    src["film"] = {
        "method": film_block["method"],
        "job_id": film_block.get("job_id"),
        "pack_id": pack_id,
    }
    note = (src.get("note") or "").rstrip()
    src["note"] = (
        f"{note} Phase 2: approximate film tags attached under sheet.film "
        "(YOLO person/ball spotting). Facts remain truth for score/cards/subs/lineups."
    ).strip()
    out["source"] = src
    return out
