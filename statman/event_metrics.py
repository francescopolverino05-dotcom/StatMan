"""StatsBomb event-stream metrics for the StatMan catalog.

Coordinates use StatsBomb open-data pitch units (120 × 80). Definitions are
documented on the ``definitions`` object returned by ``compute_match_stats``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# StatsBomb open-data pitch
SB_LENGTH = 120.0
SB_WIDTH = 80.0
FINAL_THIRD_X = 80.0  # attacking final third
PENALTY_BOX_X = 102.0  # 18 yards from goal line
PENALTY_BOX_Y0 = 18.0
PENALTY_BOX_Y1 = 62.0
# Long ball: high pass or length ≥ 30 yards (StatsBomb length unit).
LONG_BALL_LENGTH = 30.0

_SET_PIECE_PASS_TYPES = {
    "Throw-in",
    "Corner",
    "Free Kick",
    "Goal Kick",
    "Kick Off",
}


def _extra(row: pd.Series) -> dict[str, Any]:
    extra = row.get("extra")
    return extra if isinstance(extra, dict) else {}


def _name(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("name") or "")
    return ""


def _pass_block(row: pd.Series) -> dict[str, Any]:
    block = _extra(row).get("pass")
    return block if isinstance(block, dict) else {}


def _shot_block(row: pd.Series) -> dict[str, Any]:
    block = _extra(row).get("shot")
    return block if isinstance(block, dict) else {}


def _pass_complete(p: dict[str, Any]) -> bool:
    # Completed StatsBomb passes omit outcome; incomplete ones set it.
    return p.get("outcome") is None


def _period_split(mask: pd.Series, events: pd.DataFrame) -> dict[str, int]:
    if events.empty or mask is None:
        return {"first_half": 0, "second_half": 0, "total": 0}
    first = int((mask & (events["period_id"] == 1)).sum())
    second = int((mask & (events["period_id"] == 2)).sum())
    # Include ET etc. in total but keep 1H/2H as regulation halves.
    total = int(mask.sum())
    return {"first_half": first, "second_half": second, "total": total}


def _in_box(x: float, y: float) -> bool:
    return x >= PENALTY_BOX_X and PENALTY_BOX_Y0 <= y <= PENALTY_BOX_Y1


def team_event_catalog(team_events: pd.DataFrame) -> dict[str, Any]:
    """Compute the user-facing event catalog for one team from raw SB events."""
    if team_events is None or team_events.empty:
        return _empty_catalog()

    ev = team_events
    type_name = ev["type_name"] if "type_name" in ev.columns else pd.Series([], dtype=str)

    # —— Discipline / set pieces ——
    fouls_committed = int((type_name == "Foul Committed").sum())
    fouls_won = int((type_name == "Foul Won").sum())
    yellow, red = _cards(ev)
    offsides_mask = _offsides_mask(ev)
    corners_mask = _pass_type_mask(ev, "Corner")
    free_kicks = int(_pass_type_mask(ev, "Free Kick").sum())
    goal_kicks = int(_pass_type_mask(ev, "Goal Kick").sum())
    throw_ins = int(_pass_type_mask(ev, "Throw-in").sum())

    # —— Shots / attack ——
    shot_rows = ev[type_name == "Shot"]
    shot_stats = _shot_stats(shot_rows)
    key_passes = _key_passes(ev)
    into_final = _into_zone(ev, zone="final_third")
    into_box = _into_zone(ev, zone="box")

    # —— Passes ——
    open_passes = _open_play_passes(ev)
    pass_attempted = len(open_passes)
    pass_completed = sum(1 for p in open_passes if _pass_complete(p))
    prog_c, prog_a = _progressive_open_passes(ev)
    crosses_c, crosses_t = _crosses(ev)
    long_c, long_t = _long_balls(ev)
    through_c, through_t = _through_balls(ev)

    # —— Defence ——
    interceptions = int((type_name == "Interception").sum())
    recoveries = int((type_name == "Ball Recovery").sum())
    high_recoveries = _high_recoveries(ev)
    balls_lost = int((type_name.isin(["Miscontrol", "Dispossessed", "Error"])).sum())
    blocks = int((type_name == "Block").sum())
    clearances = int((type_name == "Clearance").sum())
    gk_saves = _gk_saves(ev)

    # —— Duels ——
    ground_won, ground_total = _ground_duels(ev)
    aerial_won, aerial_lost = _aerials(ev)
    aerial_total = aerial_won + aerial_lost

    return {
        "fouls_committed": fouls_committed,
        "fouls_won": fouls_won,
        "yellow_cards": yellow,
        "red_cards": red,
        "offsides": _period_split(offsides_mask, ev),
        "corners": _period_split(corners_mask, ev),
        "free_kicks": free_kicks,
        "goal_kicks": goal_kicks,
        "throw_ins": throw_ins,
        "shots_on_target": shot_stats["shots_on_target"],
        "shot_accuracy": shot_stats["shot_accuracy"],
        "blocked_shots": shot_stats["blocked_shots"],
        "missed_shots": shot_stats["missed_shots"],
        "shots_inside_box": shot_stats["shots_inside_box"],
        "shots_outside_box": shot_stats["shots_outside_box"],
        "headed_shots": shot_stats["headed_shots"],
        "shots_raw": shot_stats["shots"],
        "goals_raw": shot_stats["goals"],
        "key_passes": key_passes,
        "into_final_third_completed": into_final["completed"],
        "into_final_third_attempted": into_final["attempted"],
        "into_box_completed": into_box["completed"],
        "into_box_attempted": into_box["attempted"],
        "open_passes_attempted": pass_attempted,
        "open_passes_completed": pass_completed,
        "open_pass_accuracy": _ratio(pass_completed, pass_attempted),
        "progressive_passes_completed": prog_c,
        "progressive_passes_attempted": prog_a,
        "crosses_completed": crosses_c,
        "crosses_total": crosses_t,
        "long_balls_completed": long_c,
        "long_balls_total": long_t,
        "through_balls_completed": through_c,
        "through_balls_total": through_t,
        "interceptions_raw": interceptions,
        "recoveries": recoveries,
        "high_recoveries": high_recoveries,
        "balls_lost": balls_lost,
        "blocks": blocks,
        "clearances_raw": clearances,
        "gk_saves": gk_saves,
        "ground_duels_won": ground_won,
        "ground_duels_total": ground_total,
        "aerials_won": aerial_won,
        "aerials_lost": aerial_lost,
        "aerials_total": aerial_total,
    }


def _empty_catalog() -> dict[str, Any]:
    zero_split = {"first_half": 0, "second_half": 0, "total": 0}
    return {
        "fouls_committed": 0,
        "fouls_won": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "offsides": dict(zero_split),
        "corners": dict(zero_split),
        "free_kicks": 0,
        "goal_kicks": 0,
        "throw_ins": 0,
        "shots_on_target": 0,
        "shot_accuracy": None,
        "blocked_shots": 0,
        "missed_shots": 0,
        "shots_inside_box": 0,
        "shots_outside_box": 0,
        "headed_shots": 0,
        "shots_raw": 0,
        "goals_raw": 0,
        "key_passes": 0,
        "into_final_third_completed": 0,
        "into_final_third_attempted": 0,
        "into_box_completed": 0,
        "into_box_attempted": 0,
        "open_passes_attempted": 0,
        "open_passes_completed": 0,
        "open_pass_accuracy": None,
        "progressive_passes_completed": 0,
        "progressive_passes_attempted": 0,
        "crosses_completed": 0,
        "crosses_total": 0,
        "long_balls_completed": 0,
        "long_balls_total": 0,
        "through_balls_completed": 0,
        "through_balls_total": 0,
        "interceptions_raw": 0,
        "recoveries": 0,
        "high_recoveries": 0,
        "balls_lost": 0,
        "blocks": 0,
        "clearances_raw": 0,
        "gk_saves": 0,
        "ground_duels_won": 0,
        "ground_duels_total": 0,
        "aerials_won": 0,
        "aerials_lost": 0,
        "aerials_total": 0,
    }


def _cards(events: pd.DataFrame) -> tuple[int, int]:
    yellow = 0
    red = 0
    for _, row in events.iterrows():
        extra = _extra(row)
        for key in ("foul_committed", "bad_behaviour"):
            block = extra.get(key)
            if not isinstance(block, dict):
                continue
            card = _name(block.get("card")).lower()
            if "second yellow" in card or card == "red card":
                red += 1
            elif "yellow" in card:
                yellow += 1
    return yellow, red


def _offsides_mask(events: pd.DataFrame) -> pd.Series:
    flags = []
    for _, row in events.iterrows():
        if row.get("type_name") == "Offside":
            flags.append(True)
            continue
        if row.get("type_name") == "Pass":
            outcome = _name(_pass_block(row).get("outcome"))
            flags.append(outcome == "Pass Offside")
            continue
        flags.append(False)
    return pd.Series(flags, index=events.index)


def _pass_type_mask(events: pd.DataFrame, pass_type: str) -> pd.Series:
    flags = []
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            flags.append(False)
            continue
        flags.append(_name(_pass_block(row).get("type")) == pass_type)
    return pd.Series(flags, index=events.index)


def _shot_stats(shot_rows: pd.DataFrame) -> dict[str, Any]:
    shots = int(len(shot_rows))
    on_target = 0
    blocked = 0
    missed = 0
    goals = 0
    inside = 0
    outside = 0
    headed = 0
    for _, row in shot_rows.iterrows():
        shot = _shot_block(row)
        outcome = _name(shot.get("outcome"))
        body = _name(shot.get("body_part"))
        if outcome == "Goal":
            goals += 1
            on_target += 1
        elif outcome == "Saved" or outcome == "Saved to Post":
            on_target += 1
        elif outcome == "Blocked":
            blocked += 1
        elif outcome in {"Off T", "Wayward", "Post"}:
            missed += 1
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) >= 2:
            if _in_box(float(loc[0]), float(loc[1])):
                inside += 1
            else:
                outside += 1
        if "head" in body.lower():
            headed += 1
    return {
        "shots": shots,
        "goals": goals,
        "shots_on_target": on_target,
        "shot_accuracy": _ratio(on_target, shots),
        "blocked_shots": blocked,
        "missed_shots": missed,
        "shots_inside_box": inside,
        "shots_outside_box": outside,
        "headed_shots": headed,
    }


def _key_passes(events: pd.DataFrame) -> int:
    n = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        if p.get("shot_assist") or p.get("goal_assist") or p.get("assisted_shot_id"):
            n += 1
    return n


def _open_play_passes(events: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        if _name(p.get("type")) in _SET_PIECE_PASS_TYPES:
            continue
        out.append(p)
    return out


def _into_zone(events: pd.DataFrame, *, zone: str) -> dict[str, int]:
    completed = attempted = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        start = row.get("location")
        end = p.get("end_location")
        if not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)):
            continue
        if len(start) < 2 or len(end) < 2:
            continue
        sx, sy = float(start[0]), float(start[1])
        ex, ey = float(end[0]), float(end[1])
        if zone == "final_third":
            qualifies = sx < FINAL_THIRD_X and ex >= FINAL_THIRD_X
        else:
            qualifies = (sx < PENALTY_BOX_X or not _in_box(sx, sy)) and _in_box(ex, ey)
        if not qualifies:
            continue
        attempted += 1
        if _pass_complete(p):
            completed += 1
    return {"completed": completed, "attempted": attempted}


def _progressive_open_passes(events: pd.DataFrame) -> tuple[int, int]:
    """FBref-style progressive on StatsBomb coords (scaled to 120-length pitch).

    ≥10 yards toward goal (~10 SB units) or into the box; exclude own 40%.
    """
    completed = attempted = 0
    own_40 = 0.4 * SB_LENGTH
    prog_yards = 10.0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        if _name(p.get("type")) in _SET_PIECE_PASS_TYPES:
            continue
        start = row.get("location")
        end = p.get("end_location")
        if not isinstance(start, (list, tuple)) or not isinstance(end, (list, tuple)):
            continue
        if len(start) < 2 or len(end) < 2:
            continue
        sx, ex = float(start[0]), float(end[0])
        ey = float(end[1])
        if sx < own_40:
            continue
        advance = ex - sx
        into_box = _in_box(ex, ey)
        if advance < prog_yards and not into_box:
            continue
        attempted += 1
        if _pass_complete(p):
            completed += 1
    return completed, attempted


def _crosses(events: pd.DataFrame) -> tuple[int, int]:
    completed = total = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        if not p.get("cross"):
            continue
        total += 1
        if _pass_complete(p):
            completed += 1
    return completed, total


def _long_balls(events: pd.DataFrame) -> tuple[int, int]:
    completed = total = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        length = float(p.get("length") or 0.0)
        height = _name(p.get("height"))
        if length < LONG_BALL_LENGTH and height != "High Pass":
            continue
        total += 1
        if _pass_complete(p):
            completed += 1
    return completed, total


def _through_balls(events: pd.DataFrame) -> tuple[int, int]:
    """Count StatsBomb through-balls when the feed marks them.

    Open-data often omits ``through_ball`` / technique — then totals stay 0.
    """
    completed = total = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Pass":
            continue
        p = _pass_block(row)
        technique = _name(p.get("technique")).lower()
        flagged = bool(p.get("through_ball")) or "through" in technique
        if not flagged:
            continue
        total += 1
        if _pass_complete(p):
            completed += 1
    return completed, total


def _high_recoveries(events: pd.DataFrame) -> int:
    n = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Ball Recovery":
            continue
        loc = row.get("location")
        if isinstance(loc, (list, tuple)) and len(loc) >= 1 and float(loc[0]) >= FINAL_THIRD_X:
            n += 1
    return n


def _gk_saves(events: pd.DataFrame) -> int:
    n = 0
    for _, row in events.iterrows():
        if row.get("type_name") != "Goal Keeper":
            continue
        gk = _extra(row).get("goalkeeper")
        if isinstance(gk, dict) and _name(gk.get("type")) == "Shot Saved":
            n += 1
    return n


def _ground_duels(events: pd.DataFrame) -> tuple[int, int]:
    won = total = 0
    for _, row in events.iterrows():
        t = row.get("type_name")
        extra = _extra(row)
        if t == "Duel":
            duel = extra.get("duel")
            if not isinstance(duel, dict):
                continue
            dtype = _name(duel.get("type")).lower()
            if "aerial" in dtype:
                continue
            total += 1
            outcome = _name(duel.get("outcome")).lower()
            if outcome in {"won", "success in play", "success out"}:
                won += 1
        elif t == "50/50":
            total += 1
            block = extra.get("50_50")
            if isinstance(block, dict):
                outcome = _name(block.get("outcome")).lower()
                if "won" in outcome or "success" in outcome:
                    won += 1
        elif t == "Dribble":
            total += 1
            dribble = extra.get("dribble")
            if isinstance(dribble, dict) and _name(dribble.get("outcome")) == "Complete":
                won += 1
    return won, total


def _aerials(events: pd.DataFrame) -> tuple[int, int]:
    won = lost = 0
    for _, row in events.iterrows():
        extra = _extra(row)
        duel = extra.get("duel")
        if isinstance(duel, dict):
            duel_type = _name(duel.get("type")).lower()
            if "aerial" in duel_type:
                if "won" in duel_type:
                    won += 1
                else:
                    lost += 1
                continue
        for key in ("pass", "shot", "clearance", "miscontrol", "ball_receipt"):
            block = extra.get(key)
            if isinstance(block, dict) and block.get("aerial_won") is True:
                won += 1
                break
    return won, lost


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return round(100.0 * num / den, 1)
