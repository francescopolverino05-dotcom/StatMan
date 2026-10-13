"""Validate and normalise Phase-1 match-facts JSON."""

from __future__ import annotations

from typing import Any

EVENT_TYPES = {
    "goal",
    "yellow_card",
    "red_card",
    "substitution",
    "corner",
    "free_kick",
    "offside",
}


def _period_split(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        total = int(value)
        return {"first_half": 0, "second_half": 0, "total": total}
    if not isinstance(value, dict):
        raise ValueError("Period split must be an int or {first_half, second_half, total}")
    fh = int(value.get("first_half") or 0)
    sh = int(value.get("second_half") or 0)
    total = value.get("total")
    if total is None:
        total = fh + sh
    return {"first_half": fh, "second_half": sh, "total": int(total)}


def _lineup(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("lineup must be a list")
    out: list[dict[str, Any]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"lineup[{i}] must be an object")
        name = (row.get("player_name") or row.get("name") or "").strip()
        if not name:
            raise ValueError(f"lineup[{i}].player_name is required")
        jersey = row.get("jersey") if row.get("jersey") is not None else row.get("number")
        out.append(
            {
                "player_name": name,
                "jersey": int(jersey) if jersey is not None else None,
                "position": (row.get("position") or row.get("pos") or "").strip() or None,
                "is_starter": bool(row.get("is_starter", True)),
            }
        )
    return out


def _side(raw: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    team_name = (raw.get("team_name") or raw.get("name") or label.title()).strip()
    totals_in = raw.get("totals") or {}
    if totals_in is None:
        totals_in = {}
    if not isinstance(totals_in, dict):
        raise ValueError(f"{label}.totals must be an object")
    return {
        "team_id": int(raw["team_id"]) if raw.get("team_id") is not None else (1 if label == "home" else 2),
        "team_name": team_name,
        "formation": (raw.get("formation") or "").strip() or None,
        "lineup": _lineup(raw.get("lineup")),
        "totals": {
            "corners": _period_split(totals_in.get("corners")),
            "offsides": _period_split(totals_in.get("offsides")),
            "free_kicks": (
                int(totals_in["free_kicks"]) if totals_in.get("free_kicks") is not None else None
            ),
            "goal_kicks": (
                int(totals_in["goal_kicks"]) if totals_in.get("goal_kicks") is not None else None
            ),
            "throw_ins": (
                int(totals_in["throw_ins"]) if totals_in.get("throw_ins") is not None else None
            ),
        },
    }


def _event(raw: Any, i: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"events[{i}] must be an object")
    etype = (raw.get("type") or "").strip().lower()
    if etype not in EVENT_TYPES:
        raise ValueError(
            f"events[{i}].type must be one of {sorted(EVENT_TYPES)} (got {etype!r})"
        )
    team = (raw.get("team") or "").strip().lower()
    if team not in {"home", "away"}:
        raise ValueError(f"events[{i}].team must be 'home' or 'away'")
    minute = raw.get("minute")
    if minute is None:
        raise ValueError(f"events[{i}].minute is required")
    event: dict[str, Any] = {
        "type": etype,
        "team": team,
        "minute": int(minute),
        "second": int(raw["second"]) if raw.get("second") is not None else None,
        "player_name": (raw.get("player_name") or raw.get("player") or "").strip() or None,
        "assist_name": (raw.get("assist_name") or raw.get("assist") or "").strip() or None,
        "player_out": (raw.get("player_out") or "").strip() or None,
        "player_in": (raw.get("player_in") or "").strip() or None,
        "period": int(raw["period"]) if raw.get("period") is not None else (1 if int(minute) <= 45 else 2),
        "notes": (raw.get("notes") or "").strip() or None,
    }
    if etype == "substitution":
        if not event["player_out"] or not event["player_in"]:
            raise ValueError(f"events[{i}] substitution requires player_out and player_in")
    if etype in {"goal", "yellow_card", "red_card"} and not event["player_name"]:
        raise ValueError(f"events[{i}] {etype} requires player_name")
    return event


def parse_facts_text(raw: str | bytes) -> dict[str, Any]:
    """Parse facts JSON from uploaded text/bytes (BOM-safe, UTF-8)."""
    import json

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig")
    else:
        raw = raw.lstrip("\ufeff")
    text = raw.strip()
    if not text:
        raise ValueError("Facts file is empty")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON at line {exc.lineno} col {exc.colno}: {exc.msg}. "
            "Upload a UTF-8 .json match-facts file (see samples/napoli_pisa_primavera2_2026-10-10_facts.json)."
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Facts JSON must be an object with home, away, and events")
    return normalize_facts(payload)


def normalize_facts(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate user facts and return a canonical structure."""
    if not isinstance(payload, dict):
        raise ValueError("Facts payload must be a JSON object")
    # Tolerate wrappers like { "facts": { ... } } from some exporters.
    if "home" not in payload and isinstance(payload.get("facts"), dict):
        payload = payload["facts"]
    home = _side(payload.get("home") or {"team_name": "Home"}, label="home")
    away = _side(payload.get("away") or {"team_name": "Away"}, label="away")
    events_in = payload.get("events") or []
    if not isinstance(events_in, list):
        raise ValueError("events must be a list")
    events = [_event(e, i) for i, e in enumerate(events_in)]
    out: dict[str, Any] = {
        "competition": (payload.get("competition") or "").strip() or None,
        "season": (payload.get("season") or "").strip() or None,
        "kickoff": (payload.get("kickoff") or payload.get("game_date") or "").strip() or None,
        "venue": (payload.get("venue") or "").strip() or None,
        "home": home,
        "away": away,
        "events": events,
        "notes": (payload.get("notes") or "").strip() or None,
    }
    # Phase 2 reconcile: match-level corrected film summary (not timed fact events).
    if isinstance(payload.get("film_corrected"), dict):
        out["film_corrected"] = payload["film_corrected"]
    return out


EXAMPLE_FACTS: dict[str, Any] = {
    "competition": "Example Cup",
    "kickoff": "2018-07-14T15:00:00Z",
    "home": {
        "team_name": "Belgium",
        "formation": "3-4-2-1",
        "lineup": [
            {"player_name": "Thibaut Courtois", "jersey": 1, "position": "GK"},
            {"player_name": "Toby Alderweireld", "jersey": 2, "position": "CB"},
            {"player_name": "Vincent Kompany", "jersey": 4, "position": "CB"},
            {"player_name": "Jan Vertonghen", "jersey": 5, "position": "CB"},
            {"player_name": "Thomas Meunier", "jersey": 15, "position": "RWB"},
            {"player_name": "Axel Witsel", "jersey": 6, "position": "CM"},
            {"player_name": "Kevin De Bruyne", "jersey": 7, "position": "CM"},
            {"player_name": "Yannick Carrasco", "jersey": 11, "position": "LWB"},
            {"player_name": "Eden Hazard", "jersey": 10, "position": "AM"},
            {"player_name": "Nacer Chadli", "jersey": 22, "position": "AM"},
            {"player_name": "Romelu Lukaku", "jersey": 9, "position": "ST"},
        ],
        "totals": {
            "corners": {"first_half": 2, "second_half": 2, "total": 4},
            "offsides": {"first_half": 1, "second_half": 0, "total": 1},
            "free_kicks": 2,
        },
    },
    "away": {
        "team_name": "England",
        "formation": "3-5-2",
        "lineup": [
            {"player_name": "Jordan Pickford", "jersey": 1, "position": "GK"},
            {"player_name": "Kyle Walker", "jersey": 2, "position": "CB"},
            {"player_name": "John Stones", "jersey": 5, "position": "CB"},
            {"player_name": "Harry Maguire", "jersey": 6, "position": "CB"},
            {"player_name": "Kieran Trippier", "jersey": 12, "position": "RWB"},
            {"player_name": "Jordan Henderson", "jersey": 8, "position": "CM"},
            {"player_name": "Eric Dier", "jersey": 4, "position": "CM"},
            {"player_name": "Jesse Lingard", "jersey": 7, "position": "CM"},
            {"player_name": "Ashley Young", "jersey": 18, "position": "LWB"},
            {"player_name": "Harry Kane", "jersey": 9, "position": "ST"},
            {"player_name": "Raheem Sterling", "jersey": 10, "position": "ST"},
        ],
        "totals": {
            "corners": {"first_half": 1, "second_half": 4, "total": 5},
            "offsides": {"first_half": 0, "second_half": 0, "total": 0},
            "free_kicks": 7,
        },
    },
    "events": [
        {"type": "goal", "minute": 4, "team": "home", "player_name": "Thomas Meunier"},
        {"type": "goal", "minute": 82, "team": "home", "player_name": "Eden Hazard"},
        {
            "type": "yellow_card",
            "minute": 33,
            "team": "away",
            "player_name": "Kyle Walker",
        },
        {
            "type": "substitution",
            "minute": 46,
            "team": "home",
            "player_out": "Nacer Chadli",
            "player_in": "Marouane Fellaini",
        },
        {
            "type": "substitution",
            "minute": 70,
            "team": "away",
            "player_out": "Jesse Lingard",
            "player_in": "Marcus Rashford",
        },
    ],
}
