"""Phase 2 event taxonomy and validation.

Coordinates: ``x``/``y`` are 0..100 from the acting team's point of view,
attacking left -> right (x=100 is the opponent goal line). Optional.

Every normalised event has the shape::

    {type, team, shirt, player, t_match_seconds, x, y, attributes, confidence}

``normalize_event`` never invents values: unknown or invalid attributes are
dropped and reported in ``issues`` so the event is routed to human review.
"""

from __future__ import annotations

import math
from typing import Any

TEAMS = ("home", "away")

# type -> {attribute: spec}. spec is "bool", "float", "int", "str" or a tuple of allowed values.
TAXONOMY: dict[str, dict[str, Any]] = {
    "goal": {"own_goal": "bool", "headed": "bool"},
    "pass": {
        "completed": "bool",
        "key_pass": "bool",
        "progressive": "bool",
        "line_broken": ("midfield", "defence", "attack", "multiple"),
        "cross": "bool",
        "box_entry": "bool",
    },
    "shot": {
        "xg": "float",
        "on_target": "bool",
        "outcome": ("goal", "saved", "blocked", "missed", "post"),
        "headed": "bool",
        "inside_box": "bool",
    },
    "corner": {},
    "foul": {},
    "card": {"color": ("yellow", "red")},
    "free_kick": {"distance_m": "float", "outcome": ("direct_shot", "crossed_played")},
    "tackle": {"won": "bool"},
    "interception": {},
    "ball_lost": {"reason": ("miscontrol", "dispossessed")},
    "aerial_duel": {"won": "bool", "source": ("goal_kick", "long_ball")},
    "save": {},
    "goal_conceded": {},
    "gk_pass": {"length": ("short", "long"), "lane": ("middle", "flank"), "completed": "bool"},
}

# Attributes a reviewer needs before the event can be trusted.
REQUIRED: dict[str, tuple[str, ...]] = {
    "pass": ("completed",),
    "shot": ("on_target",),
    "card": ("color",),
    "free_kick": ("outcome",),
    "ball_lost": ("reason",),
    "aerial_duel": ("won",),
    "gk_pass": ("length",),
}

FREE_KICK_MAX_DISTANCE_M = 30.0
EVENT_TYPES = tuple(TAXONOMY)


def _coerce(value: Any, spec: Any) -> tuple[bool, Any]:
    if value is None:
        return False, None
    if isinstance(spec, tuple):
        v = str(value).strip().lower()
        return (v in spec), v
    if spec == "bool":
        if isinstance(value, bool):
            return True, value
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return True, value.lower() == "true"
        return False, None
    if spec == "float":
        try:
            f = float(value)
        except (TypeError, ValueError):
            return False, None
        return (math.isfinite(f)), f
    if spec == "int":
        try:
            return True, int(value)
        except (TypeError, ValueError):
            return False, None
    return True, str(value)


def _opt_float(value: Any, lo: float | None = None, hi: float | None = None) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if lo is not None and hi is not None:
        f = min(max(f, lo), hi)
    return f


def _opt_shirt(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 100 else None


def normalize_event(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate one tagger event. Returns (event or None if unusable, issues)."""

    issues: list[str] = []
    etype = str(raw.get("type") or "").strip().lower()
    if etype not in TAXONOMY:
        return None, [f"unknown type {etype!r}"]
    team = str(raw.get("team") or "").strip().lower() or None
    if team not in TEAMS:
        issues.append("team missing or not home/away")
        team = None
    t = _opt_float(raw.get("t_match_seconds"))
    if t is None or t < 0:
        return None, ["missing t_match_seconds"]
    conf = _opt_float(raw.get("confidence"), 0.0, 1.0)
    if conf is None:
        issues.append("missing confidence")
        conf = 0.0

    attrs_in = raw.get("attributes") or {}
    if not isinstance(attrs_in, dict):
        attrs_in = {}
    spec = TAXONOMY[etype]
    attrs: dict[str, Any] = {}
    for key, value in attrs_in.items():
        if key not in spec:
            issues.append(f"dropped unknown attribute {key}")
            continue
        if value is None:
            continue
        ok, coerced = _coerce(value, spec[key])
        if not ok:
            issues.append(f"invalid {key}={value!r}")
            continue
        attrs[key] = coerced

    # Type-specific rules from the stat definitions.
    if etype == "shot":
        if attrs.get("outcome") in {"blocked", "missed", "post"}:
            attrs["on_target"] = False
        elif attrs.get("outcome") in {"goal", "saved"}:
            attrs["on_target"] = True
        if "xg" in attrs:
            attrs["xg"] = min(max(attrs["xg"], 0.0), 1.0)
    if etype == "pass":
        if attrs.get("line_broken") and "progressive" not in attrs:
            attrs["progressive"] = True
        if attrs.get("progressive") and not attrs.get("line_broken"):
            issues.append("progressive pass without line_broken")
    if etype == "free_kick":
        dist = attrs.get("distance_m")
        if dist is not None and dist > FREE_KICK_MAX_DISTANCE_M:
            return None, [f"free kick at {dist} m is outside {FREE_KICK_MAX_DISTANCE_M} m"]
        if dist is None:
            issues.append("free kick distance unknown")
    for key in REQUIRED.get(etype, ()):
        if key not in attrs:
            issues.append(f"missing {key}")

    x = _opt_float(raw.get("x"), 0.0, 100.0)
    y = _opt_float(raw.get("y"), 0.0, 100.0)
    player = raw.get("player")
    event = {
        "type": etype,
        "team": team,
        "shirt": _opt_shirt(raw.get("shirt", raw.get("player_shirt"))),
        "player": str(player).strip() if isinstance(player, str) and player.strip() else None,
        "t_match_seconds": round(t, 2),
        "x": x,
        "y": y,
        "attributes": attrs,
        "confidence": round(conf, 3),
    }
    return event, issues


def json_schema() -> dict[str, Any]:
    """Strict JSON schema for the tagger response (OpenAI ``json_schema`` format)."""

    attr_props: dict[str, Any] = {}
    for spec in TAXONOMY.values():
        for key, kind in spec.items():
            if isinstance(kind, tuple):
                attr_props[key] = {"type": ["string", "null"], "enum": [*kind, None]}
            elif kind == "bool":
                attr_props[key] = {"type": ["boolean", "null"]}
            elif kind == "float":
                attr_props[key] = {"type": ["number", "null"]}
            else:
                attr_props[key] = {"type": ["string", "null"]}
    event = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "team", "shirt", "t_clip_seconds", "x", "y", "attributes", "confidence"],
        "properties": {
            "type": {"type": "string", "enum": list(EVENT_TYPES)},
            "team": {"type": "string", "enum": list(TEAMS)},
            "shirt": {"type": ["integer", "null"]},
            "t_clip_seconds": {"type": "number"},
            "x": {"type": ["number", "null"]},
            "y": {"type": ["number", "null"]},
            "attributes": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(attr_props),
                "properties": attr_props,
            },
            "confidence": {"type": "number"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["events"],
        "properties": {"events": {"type": "array", "items": event}},
    }
