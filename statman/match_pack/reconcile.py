"""Reconcile Phase-2 film tags against fact events, then optionally promote into facts.

Facts stay authoritative for goals, cards, substitutions, lineups, and score.
Film tags have no team/player identity — they cannot be copied wholesale into
``facts.events``. This module:

1. Anchors film ``Goal`` tags to fact goals by minute (timeline correction).
2. Builds corrected match-level film totals (goal tags forced to the fact count).
3. Optionally writes a ``film_corrected`` block into the facts JSON for the editor.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from statman.match_pack import store
from statman.match_pack.film_merge import merge_film_into_sheet
from statman.match_pack.pipeline import put_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts

# Broadcast clock ≈ match minute for many feeds; allow a few minutes of drift / stoppage.
GOAL_ANCHOR_WINDOW_MIN = 4.0


def _film_events_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_events.json"


def _film_stats_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_stats.json"


def _corrected_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_corrected.json"


def reconcile_film_with_facts(
    facts: dict[str, Any],
    film_events: list[dict[str, Any]],
    film_stats: dict[str, Any] | None = None,
    *,
    goal_window_min: float = GOAL_ANCHOR_WINDOW_MIN,
) -> dict[str, Any]:
    """Return a corrected film summary anchored to fact goals/cards/subs."""
    fact_events = list(facts.get("events") or [])
    fact_goals = [e for e in fact_events if e.get("type") == "goal"]
    fact_cards = [e for e in fact_events if e.get("type") in {"yellow_card", "red_card"}]
    fact_subs = [e for e in fact_events if e.get("type") == "substitution"]

    goal_tags = [e for e in film_events if e.get("label") == "Goal"]
    anchored: list[dict[str, Any]] = []
    used_idx: set[int] = set()

    for fg in fact_goals:
        target = float(fg.get("minute") or 0)
        best_i = None
        best_dist = None
        for i, tag in enumerate(goal_tags):
            if i in used_idx:
                continue
            film_min = float(tag.get("time_sec") or 0) / 60.0
            dist = abs(film_min - target)
            if dist <= goal_window_min and (best_dist is None or dist < best_dist):
                best_dist = dist
                best_i = i
        if best_i is None:
            anchored.append(
                {
                    "fact_minute": fg.get("minute"),
                    "team": fg.get("team"),
                    "player_name": fg.get("player_name"),
                    "assist_name": fg.get("assist_name"),
                    "film_time_sec": None,
                    "film_minute": None,
                    "matched": False,
                    "notes": "No film Goal tag within window — fact goal kept as truth",
                }
            )
            continue
        used_idx.add(best_i)
        tag = goal_tags[best_i]
        film_min = float(tag.get("time_sec") or 0) / 60.0
        anchored.append(
            {
                "fact_minute": fg.get("minute"),
                "team": fg.get("team"),
                "player_name": fg.get("player_name"),
                "assist_name": fg.get("assist_name"),
                "film_time_sec": tag.get("time_sec"),
                "film_minute": round(film_min, 2),
                "matched": True,
                "confidence": tag.get("confidence"),
                "notes": f"Anchored film Goal tag ({best_dist:.1f}' from fact minute)",
            }
        )

    raw_totals = ((film_stats or {}).get("totals") or {}) if film_stats else {}
    # Prefer film_stats totals; fall back to counting events.
    if not raw_totals and film_events:
        from collections import Counter

        counts = Counter(e.get("label") for e in film_events)
        raw_totals = {
            "events": len(film_events),
            "shots": counts.get("Shot", 0) + counts.get("Goal", 0),
            "passes": (
                counts.get("Pass", 0)
                + counts.get("High Pass", 0)
                + counts.get("Cross", 0)
                + counts.get("Throw In", 0)
                + counts.get("Free Kick", 0)
            ),
            "crosses": counts.get("Cross", 0),
            "high_passes": counts.get("High Pass", 0),
            "drives": counts.get("Drive", 0),
            "headers": counts.get("Header", 0),
            "tackles": counts.get("Player Successful Tackle", 0),
            "blocks": counts.get("Ball Player Block", 0),
            "throw_ins": counts.get("Throw In", 0),
            "free_kicks": counts.get("Free Kick", 0),
            "outs": counts.get("Out", 0),
            "goals": counts.get("Goal", 0),
        }

    corrected_totals = {
        "events": raw_totals.get("events") or len(film_events),
        # Goals: facts win.
        "goals": len(fact_goals),
        "goal_tags_raw": len(goal_tags),
        "goal_tags_matched": sum(1 for a in anchored if a.get("matched")),
        # Shots stay approximate until a better model / manual edit.
        "shots": raw_totals.get("shots"),
        "shots_status": "approximate_uncorrected",
        "passes": raw_totals.get("passes"),
        "passes_status": "approximate_uncorrected",
        "crosses": raw_totals.get("crosses"),
        "drives": raw_totals.get("drives"),
        "headers": raw_totals.get("headers"),
        "tackles": raw_totals.get("tackles"),
        "blocks": raw_totals.get("blocks"),
        "throw_ins": raw_totals.get("throw_ins"),
        "free_kicks": raw_totals.get("free_kicks"),
        "outs": raw_totals.get("outs"),
    }

    return {
        "phase": "match-pack-phase2-reconcile",
        "quality": "facts_plus_corrected_film",
        "created_at": time.time(),
        "rules": {
            "goals": "Fact goals are truth; film Goal tags only used for timeline anchoring.",
            "cards_subs": "Fact cards/substitutions unchanged — film has no card/sub labels.",
            "shots_passes": (
                "Left as approximate film counts (no team/player). "
                "Do not treat as Opta. Edit manually in facts.film_corrected if you have real totals."
            ),
            "promotion": (
                "Safe to store under facts.film_corrected (match-level). "
                "Not copied into facts.events (schema needs team + player)."
            ),
        },
        "fact_event_counts": {
            "goals": len(fact_goals),
            "cards": len(fact_cards),
            "substitutions": len(fact_subs),
        },
        "anchored_goals": anchored,
        "corrected_totals": corrected_totals,
        "raw_film_totals": {
            "goal_tags": len(goal_tags),
            "shots": raw_totals.get("shots"),
            "passes": raw_totals.get("passes"),
            "throw_ins": raw_totals.get("throw_ins"),
            "events": raw_totals.get("events") or len(film_events),
        },
    }


def promote_corrected_into_facts(
    facts: dict[str, Any],
    corrected: dict[str, Any],
    *,
    promote_set_pieces: bool = True,
) -> dict[str, Any]:
    """Attach ``film_corrected`` to facts. Optionally fill empty throw_in/FK totals.

    Set pieces are match-level film counts — written into facts notes metadata only
    under ``film_corrected``; we do **not** invent home/away splits on side.totals
    (that would double-count on the team board).
    """
    out = dict(facts)
    block = {
        "phase": corrected.get("phase"),
        "quality": corrected.get("quality"),
        "rules": corrected.get("rules"),
        "anchored_goals": corrected.get("anchored_goals"),
        "match_totals": corrected.get("corrected_totals"),
        "raw_film_totals": corrected.get("raw_film_totals"),
        "promoted_at": time.time(),
    }
    if promote_set_pieces:
        block["set_pieces_note"] = (
            "throw_ins/free_kicks below are match-level film estimates — not assigned to a team."
        )
    out["film_corrected"] = block
    # Keep human-readable note.
    note = (out.get("notes") or "").rstrip()
    goals = (corrected.get("fact_event_counts") or {}).get("goals")
    matched = (corrected.get("corrected_totals") or {}).get("goal_tags_matched")
    addon = (
        f" Film reconciled: {matched}/{goals} fact goals anchored to film Goal tags; "
        "score/cards/subs remain fact truth."
    )
    if addon.strip() not in note:
        out["notes"] = f"{note}{addon}".strip() if note else addon.strip()
    return out


def reconcile_pack(pack_id: str, *, promote: bool = True) -> dict[str, Any]:
    """Run reconcile on a pack; optionally promote into facts and refresh the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    facts = meta.get("facts")
    if not facts:
        raise ValueError("Upload match facts before reconciling film tags")
    events_path = _film_events_path(pack_id)
    if not events_path.exists():
        raise ValueError("No film events on this pack — run Analyze / import first")
    film_events = json.loads(events_path.read_text(encoding="utf-8"))
    film_stats = None
    if _film_stats_path(pack_id).exists():
        film_stats = json.loads(_film_stats_path(pack_id).read_text(encoding="utf-8"))

    corrected = reconcile_film_with_facts(facts, film_events, film_stats)
    _corrected_path(pack_id).write_text(
        json.dumps(corrected, indent=2, default=str), encoding="utf-8"
    )

    if promote:
        new_facts = promote_corrected_into_facts(facts, corrected)
        meta = put_facts(pack_id, new_facts)
        facts = meta["facts"]

    # Refresh sheet: facts + film + corrected overlay on film block.
    sheet = sheet_from_facts(facts, pack_id=pack_id)
    if film_stats is not None:
        sheet = merge_film_into_sheet(sheet, film_stats, pack_id=pack_id)
    film_block = dict(sheet.get("film") or {})
    film_block["corrected"] = {
        "goals": corrected["corrected_totals"]["goals"],
        "goal_tags_raw": corrected["corrected_totals"]["goal_tags_raw"],
        "goal_tags_matched": corrected["corrected_totals"]["goal_tags_matched"],
        "anchored_goals": corrected["anchored_goals"],
        "shots": corrected["corrected_totals"]["shots"],
        "shots_status": corrected["corrected_totals"]["shots_status"],
        "passes": corrected["corrected_totals"]["passes"],
        "passes_status": corrected["corrected_totals"]["passes_status"],
        "throw_ins": corrected["corrected_totals"]["throw_ins"],
        "free_kicks": corrected["corrected_totals"]["free_kicks"],
    }
    film_block["warning"] = (
        "Corrected against match facts: goal count follows facts "
        f"({corrected['corrected_totals']['goals']}); "
        f"{corrected['corrected_totals']['goal_tags_matched']} film Goal tag(s) anchored. "
        "Shot/pass totals remain approximate film counts (no team split). "
        "Full corrected block is in facts.film_corrected."
    )
    sheet["film"] = film_block
    src = dict(sheet.get("source") or {})
    src["phase"] = "match-pack-phase2-reconcile"
    src["quality"] = "fact_plus_corrected_film"
    cov = dict(src.get("coverage") or {})
    cov["reconciled"] = ["goals_anchored", "film_corrected_in_facts"]
    src["coverage"] = cov
    sheet["source"] = src

    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta = store.read_meta(pack_id) or meta
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["film_corrected_path"] = str(_corrected_path(pack_id))
    meta["status"] = "phase2_reconciled"
    meta["phase"] = "match-pack-phase2-reconcile"
    meta["coverage"] = sheet["source"]["coverage"]
    meta["reconcile"] = {
        "status": "done",
        "promoted": bool(promote),
        "goal_tags_matched": corrected["corrected_totals"]["goal_tags_matched"],
        "fact_goals": corrected["fact_event_counts"]["goals"],
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)
    return meta
