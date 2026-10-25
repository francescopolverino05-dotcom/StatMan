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
    # Added for the analyst-style (code) tagger. Stats use them via their codes (THROW/GOALKICK = passes, DUEL won = PPDA action).
    "duel": {"won": "bool"},
    "throw_in": {"completed": "bool"},
    "goal_kick": {"completed": "bool"},
    "clearance": {},
    "recovery": {},
    "gap": {},  # camera off the ball / replay: nothing can be tagged here
}

# Analyst event codes the model returns -> internal taxonomy type.
CODES: dict[str, str] = {
    "PASS": "pass", "CROSS": "pass", "SHOT": "shot", "SAVE": "save", "TACKLE": "tackle",
    "INTERCEPT": "interception", "AERIAL": "aerial_duel", "DUEL": "duel", "FOUL": "foul", "CARD": "card",
    "CORNER": "corner", "FK": "free_kick", "THROW": "throw_in", "GOALKICK": "goal_kick", "GK_PASS": "gk_pass",
    "CLEAR": "clearance", "RECOVERY": "recovery", "LOST": "ball_lost", "GAP": "gap",
}
OUTCOMES = ("success", "fail", "on", "off", "blocked", "goal", "post", "yellow", "red")

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
    x2 = _opt_float(raw.get("x2"), 0.0, 100.0)
    y2 = _opt_float(raw.get("y2"), 0.0, 100.0)
    outcome = str(raw.get("outcome") or "").strip().lower() or None
    if outcome is not None and outcome not in OUTCOMES:
        issues.append(f"invalid outcome={outcome!r}")
        outcome = None
    code = str(raw.get("code") or "").strip().upper() or None
    detail = raw.get("detail")
    player = raw.get("player")
    event = {
        "type": etype,
        "team": team,
        "shirt": _opt_shirt(raw.get("shirt", raw.get("player_shirt"))),
        "player": str(player).strip() if isinstance(player, str) and player.strip() else None,
        "t_match_seconds": round(t, 2),
        "x": x,
        "y": y,
        "x2": x2,
        "y2": y2,
        "outcome": outcome,
        "code": code,
        "detail": str(detail).strip() if isinstance(detail, str) and detail.strip() else None,
        "attributes": attrs,
        "confidence": round(conf, 3),
    }
    return event, issues


_SUCCESS = {"success": True, "fail": False}


def clock_to_seconds(value: Any) -> float | None:
    """'37:12' / '90+2:05' / '37' (minutes) / 2232 (seconds as number) -> seconds."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    text = str(value).strip().replace("'", "")
    plus = 0.0
    if "+" in text:  # stoppage time: 45+2:10 -> 47:10
        base, _, rest = text.partition("+")
        try:
            extra_min, _, extra_sec = rest.partition(":")
            plus = float(extra_min or 0) * 60 + float(extra_sec or 0)
            return float(base) * 60 + plus
        except ValueError:
            return None
    parts = text.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0] * 60
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


def from_code_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Translate one analyst-code event (code/outcome/x1..y2) into a raw taxonomy event.

    The result still goes through ``normalize_event`` later. ``None`` for an
    unknown code. Keeps ``code``, ``outcome``, ``detail``, ``x2``, ``y2``.
    """

    code = str(raw.get("code") or raw.get("type") or "").strip().upper().replace(" ", "_").replace("-", "_")
    code = {"INTERCEPTION": "INTERCEPT", "CLEARANCE": "CLEAR", "THROW_IN": "THROW", "GOAL_KICK": "GOALKICK",
            "FREE_KICK": "FK", "AERIAL_DUEL": "AERIAL", "BALL_LOST": "LOST"}.get(code, code)
    etype = CODES.get(code)
    if etype is None:
        return None
    outcome = str(raw.get("outcome") or "").strip().lower() or None
    detail = str(raw.get("detail") or "")
    low = detail.lower()
    attrs: dict[str, Any] = {}
    ok = _SUCCESS.get(outcome or "")
    if etype == "pass":
        if ok is not None:
            attrs["completed"] = ok
        if code == "CROSS":
            attrs["cross"] = True
    elif etype == "shot":
        attrs["outcome"] = {"goal": "goal", "on": "saved", "off": "missed", "blocked": "blocked",
                            "post": "post", "fail": "missed"}.get(outcome or "")
        if outcome == "on" and "goal" in low and "no goal" not in low:
            attrs["outcome"] = "goal"
        if "head" in low:
            attrs["headed"] = True
    elif etype in {"tackle", "aerial_duel", "duel"}:
        if ok is not None:
            attrs["won"] = ok
    elif etype in {"gk_pass", "throw_in", "goal_kick"}:
        if ok is not None:
            attrs["completed"] = ok
    elif etype == "card":
        color = outcome if outcome in {"yellow", "red"} else ("red" if "red" in low else "yellow" if "yellow" in low else None)
        attrs["color"] = color
    elif etype == "ball_lost":
        if "control" in low or "touch" in low:
            attrs["reason"] = "miscontrol"
        elif "dispossess" in low or "tackled" in low or "lost it" in low:
            attrs["reason"] = "dispossessed"

    x1, y1 = raw.get("x1", raw.get("x")), raw.get("y1", raw.get("y"))
    x2, y2 = raw.get("x2"), raw.get("y2")
    if etype == "gk_pass":
        try:
            dist = math.hypot(float(x2) - float(x1), float(y2) - float(y1))
            attrs["length"] = "long" if dist >= 35 else "short"
            attrs["lane"] = "middle" if 30 <= float(y2) <= 70 else "flank"
        except (TypeError, ValueError):
            pass
    shirt = raw.get("shirt", raw.get("number"))
    out = {
        "type": etype, "code": code, "team": raw.get("team"), "shirt": shirt, "player": raw.get("player"),
        "x": x1, "y": y1, "x2": x2, "y2": y2, "outcome": outcome, "detail": detail or None,
        "attributes": {k: v for k, v in attrs.items() if v is not None},
        "confidence": 1.0 if etype == "gap" and raw.get("confidence") is None else raw.get("confidence"),
    }
    for key in ("t_clip_seconds", "t_match_seconds", "clock"):
        if raw.get(key) is not None:
            out[key] = raw[key]
    return out


def code_json_schema() -> dict[str, Any]:
    """Strict schema for the analyst-code tagger: {"events": [...]}."""

    num = {"type": ["number", "null"]}
    event = {
        "type": "object",
        "additionalProperties": False,
        "required": ["clock", "team", "code", "player", "shirt", "outcome", "x1", "y1", "x2", "y2",
                     "detail", "confidence"],
        "properties": {
            "clock": {"type": "string", "description": "match clock mm:ss"},
            "team": {"type": "string", "enum": list(TEAMS)},
            "code": {"type": "string", "enum": list(CODES)},
            "player": {"type": ["string", "null"]},
            "shirt": {"type": ["integer", "null"]},
            "outcome": {"type": ["string", "null"], "enum": [*OUTCOMES, None]},
            "x1": num, "y1": num, "x2": num, "y2": num,
            "detail": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["events"],
        "properties": {"events": {"type": "array", "items": event}},
    }


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
