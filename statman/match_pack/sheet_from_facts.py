"""Build a Phase-1 match sheet from user-supplied match facts.

Fields filled from facts are marked ``fact`` in provenance. Everything else is
``pending`` (later phases: tracking / ball-action models).
"""

from __future__ import annotations

from typing import Any

from statman.compute import CATALOG_VERSION

PHASE = "match-pack-phase1"


def _empty_split() -> dict[str, int | None]:
    return {"first_half": None, "second_half": None, "total": None}


def _prov(status: str, *, detail: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"status": status, "phase": PHASE}
    if detail:
        row["detail"] = detail
    return row


def _count_events(events: list[dict[str, Any]], etype: str, team: str) -> int:
    return sum(1 for e in events if e.get("type") == etype and e.get("team") == team)


def _team_block(
    side_key: str,
    side: dict[str, Any],
    other: dict[str, Any],
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (team_stats, provenance_for_team)."""
    goals = _count_events(events, "goal", side_key)
    yellow = _count_events(events, "yellow_card", side_key)
    red = _count_events(events, "red_card", side_key)
    conceded = _count_events(events, "goal", "away" if side_key == "home" else "home")
    totals = side.get("totals") or {}
    corners = totals.get("corners")
    offsides = totals.get("offsides")
    free_kicks = totals.get("free_kicks")
    goal_kicks = totals.get("goal_kicks")
    throw_ins = totals.get("throw_ins")

    # Timed corner/offside/fk events can fill totals when explicit totals omit them.
    timed_corners = _count_events(events, "corner", side_key)
    timed_offsides = _count_events(events, "offside", side_key)
    timed_fk = _count_events(events, "free_kick", side_key)

    if corners is None and timed_corners:
        corners = {"first_half": 0, "second_half": 0, "total": timed_corners}
        for e in events:
            if e.get("type") == "corner" and e.get("team") == side_key:
                if int(e.get("period") or 1) == 1:
                    corners["first_half"] += 1
                else:
                    corners["second_half"] += 1
        corners["total"] = corners["first_half"] + corners["second_half"]
    if offsides is None and timed_offsides:
        offsides = {"first_half": 0, "second_half": 0, "total": timed_offsides}
        for e in events:
            if e.get("type") == "offside" and e.get("team") == side_key:
                if int(e.get("period") or 1) == 1:
                    offsides["first_half"] += 1
                else:
                    offsides["second_half"] += 1
        offsides["total"] = offsides["first_half"] + offsides["second_half"]
    if free_kicks is None and timed_fk:
        free_kicks = timed_fk

    prov: dict[str, Any] = {
        "goals": _prov("fact", detail="counted from events[].type=goal"),
        "yellow_cards": _prov("fact", detail="counted from events[].type=yellow_card"),
        "red_cards": _prov("fact", detail="counted from events[].type=red_card"),
        "goals_conceded": _prov("fact", detail="opponent goals from events"),
        "formation": _prov("fact" if side.get("formation") else "missing"),
        "lineup": _prov("fact" if side.get("lineup") else "missing"),
        "corners": _prov("fact" if corners is not None else "missing"),
        "offsides": _prov("fact" if offsides is not None else "missing"),
        "free_kicks": _prov("fact" if free_kicks is not None else "missing"),
        "goal_kicks": _prov("fact" if goal_kicks is not None else "missing"),
        "throw_ins": _prov("fact" if throw_ins is not None else "missing"),
        # Pending until later phases.
        "possession_pct": _prov("pending", detail="needs tracking (phase 3)"),
        "xg": _prov("pending", detail="needs shot model (phase 4–5)"),
        "shots": _prov("pending"),
        "pass_accuracy": _prov("pending", detail="needs ball-action + success (phase 4)"),
        "progressive_passes": _prov("pending"),
        "ppda": _prov("pending", detail="needs tracking + defence events (phase 3–5)"),
        "aerials_won": _prov("pending"),
        "tackles": _prov("pending"),
        "interceptions": _prov("pending"),
        "clearances": _prov("pending"),
    }

    team = {
        "team_id": side["team_id"],
        "team_name": side["team_name"],
        "formation": side.get("formation"),
        "lineup": side.get("lineup") or [],
        "goals": goals,
        "goals_conceded": conceded,
        "yellow_cards": yellow,
        "red_cards": red,
        "possession_pct": None,
        "fouls_committed": None,
        "fouls_won": None,
        "offsides": offsides or _empty_split(),
        "corners": corners or _empty_split(),
        "free_kicks": free_kicks,
        "goal_kicks": goal_kicks,
        "throw_ins": throw_ins,
        "xg": None,
        "shots": None,
        "shots_on_target": None,
        "shot_accuracy": None,
        "passes_attempted": None,
        "passes_completed": None,
        "pass_accuracy": None,
        "progressive_passes": None,
        "progressive_passes_completed": None,
        "progressive_passes_attempted": None,
        "tackles": None,
        "interceptions": None,
        "recoveries": None,
        "blocks": None,
        "clearances": None,
        "aerials_won": None,
        "aerials_total": None,
        "ppda": None,
        "shots_faced": None,
        "shots_on_target_faced": None,
        "saves": None,
        "save_pct": None,
        "sections": {
            "match": {
                "goals": goals,
                "possession_pct": None,
                "fouls_committed": None,
                "fouls_won": None,
                "yellow_cards": yellow,
                "red_cards": red,
                "offsides": offsides or _empty_split(),
                "corners": corners or _empty_split(),
                "free_kicks": free_kicks,
                "goal_kicks": goal_kicks,
                "throw_ins": throw_ins,
            },
            "attack": {
                "xg": None,
                "shots": None,
                "shots_on_target": None,
                "shot_accuracy": None,
            },
            "passes": {
                "passes_attempted": None,
                "passes_completed": None,
                "pass_accuracy": None,
                "progressive_passes_completed": None,
                "progressive_passes_attempted": None,
            },
            "defence": {
                "tackles": None,
                "interceptions": None,
                "aerials_won": None,
                "aerials_total": None,
                "ppda": None,
            },
            "goalkeeper": {
                "goals_conceded": conceded,
                "shots_faced": None,
                "saves": None,
                "save_pct": None,
            },
        },
        "provenance": prov,
    }
    # silence unused — other side reserved for future head-to-head derived fields
    _ = other
    return team, prov


def sheet_from_facts(facts: dict[str, Any], *, pack_id: str) -> dict[str, Any]:
    """Return a StatMan-shaped stats payload sourced only from match facts."""
    home_side = facts["home"]
    away_side = facts["away"]
    events = facts.get("events") or []
    home, home_prov = _team_block("home", home_side, away_side, events)
    away, away_prov = _team_block("away", away_side, home_side, events)

    fact_fields = [
        k for k, v in home_prov.items() if v.get("status") == "fact"
    ]
    pending_fields = [
        k for k, v in home_prov.items() if v.get("status") == "pending"
    ]
    missing_fields = [
        k for k, v in home_prov.items() if v.get("status") == "missing"
    ]

    subs = [e for e in events if e["type"] == "substitution"]
    goals = [e for e in events if e["type"] == "goal"]
    cards = [e for e in events if e["type"] in {"yellow_card", "red_card"}]

    coverage = {
        "fact": sorted(set(fact_fields)),
        "missing_optional": sorted(set(missing_fields)),
        "pending_later_phases": sorted(set(pending_fields)),
        "fact_event_counts": {
            "goals": len(goals),
            "cards": len(cards),
            "substitutions": len(subs),
            "events_total": len(events),
        },
    }

    return {
        "source": {
            "provider": "match-pack-facts",
            "quality": "fact_sourced",
            "phase": PHASE,
            "catalog_version": CATALOG_VERSION,
            "pack_id": pack_id,
            "note": (
                "Phase 1: goals, cards, substitutions, lineups/formations, and optional "
                "set-piece totals come from your match facts (treated as truth). "
                "Possession, xG, pass accuracy, progressive passes, PPDA, and aerials "
                "stay pending until tracking and ball-action phases."
            ),
            "coverage": coverage,
        },
        "catalog_version": CATALOG_VERSION,
        "match": {
            "pack_id": pack_id,
            "competition": facts.get("competition"),
            "season": facts.get("season"),
            "kickoff": facts.get("kickoff"),
            "venue": facts.get("venue"),
            "home_team": home_side["team_name"],
            "away_team": away_side["team_name"],
            "home_team_id": home_side["team_id"],
            "away_team_id": away_side["team_id"],
            "home_score": home["goals"],
            "away_score": away["goals"],
            "home_formation": home_side.get("formation"),
            "away_formation": away_side.get("formation"),
        },
        "teams": [home, away],
        "events": events,
        "substitutions": subs,
        "goal_events": goals,
        "card_events": cards,
        "players": _players_from_lineups(home_side, away_side, events),
    }


def _players_from_lineups(
    home: dict[str, Any],
    away: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for side_key, side in (("home", home), ("away", away)):
        for p in side.get("lineup") or []:
            name = p["player_name"]
            goals = sum(
                1
                for e in events
                if e["type"] == "goal"
                and e["team"] == side_key
                and (e.get("player_name") or "").lower() == name.lower()
            )
            yellow = sum(
                1
                for e in events
                if e["type"] == "yellow_card"
                and e["team"] == side_key
                and (e.get("player_name") or "").lower() == name.lower()
            )
            red = sum(
                1
                for e in events
                if e["type"] == "red_card"
                and e["team"] == side_key
                and (e.get("player_name") or "").lower() == name.lower()
            )
            rows.append(
                {
                    "player_name": name,
                    "team_name": side["team_name"],
                    "team_id": side["team_id"],
                    "jersey": p.get("jersey"),
                    "position": p.get("position"),
                    "is_starter": p.get("is_starter", True),
                    "goals": goals,
                    "yellow_cards": yellow,
                    "red_cards": red,
                    "provenance": "fact",
                }
            )
    return rows
