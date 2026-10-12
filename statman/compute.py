"""Derive StatMan match stats from SPADL actions and raw StatsBomb events."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from statman.event_metrics import team_event_catalog
from statman.load import MatchBundle

FIELD_LENGTH = 105.0
FIELD_WIDTH = 68.0
# FBref-style progressive pass: ≥10 yards (~9.14 m) toward goal, or into the box.
PROGRESSIVE_YARDS_M = 10 * 0.9144
PENALTY_BOX_X = FIELD_LENGTH - 16.5
# PPDA zone: opponent passes in their own 60% of the pitch.
PPDA_OWN_ZONE_X = 0.6 * FIELD_LENGTH

CATALOG_DEFINITIONS: dict[str, str] = {
    "goals": "Shot events with outcome Goal (StatsBomb).",
    "possession_pct": "Share of StatsBomb possession-chain duration by team (full match).",
    "fouls_committed": "StatsBomb Foul Committed events.",
    "fouls_won": "StatsBomb Foul Won events.",
    "yellow_cards": "Yellow cards on Foul Committed or Bad Behaviour.",
    "red_cards": "Red / second-yellow cards on Foul Committed or Bad Behaviour.",
    "offsides": "Pass Offside outcomes + Offside events, split by period (1H / 2H / total).",
    "corners": "Pass type Corner, split by period (1H / 2H / total).",
    "free_kicks": "Pass type Free Kick (excludes goal kicks).",
    "goal_kicks": "Pass type Goal Kick.",
    "throw_ins": "Pass type Throw-in.",
    "xg": "Sum of StatsBomb shot.statsbomb_xg on shot events.",
    "shots": "StatsBomb Shot events (full match).",
    "shots_on_target": "Shot outcomes Goal, Saved, Saved to Post.",
    "shot_accuracy": "Shots on target / shots × 100.",
    "blocked_shots": "Shot outcome Blocked.",
    "missed_shots": "Shot outcomes Off T, Wayward, Post.",
    "shots_inside_box": "Shots with location inside the StatsBomb penalty area.",
    "shots_outside_box": "Shots with location outside the StatsBomb penalty area.",
    "headed_shots": "Shots with body part Head.",
    "key_passes": "Passes with shot_assist, goal_assist, or assisted_shot_id.",
    "into_final_third": (
        "Completed / attempted passes that start before x=80 and end at x≥80 "
        "(StatsBomb pitch)."
    ),
    "into_box": (
        "Completed / attempted passes that end inside the StatsBomb penalty box."
    ),
    "passes": (
        "Open-play Pass events (excludes throw-in, corner, free kick, goal kick, kick-off)."
    ),
    "pass_accuracy": "Open-play passes completed / attempted × 100 (full match).",
    "progressive_passes": (
        "Open-play passes advancing ≥10 yards toward goal or into the box, "
        "excluding starts in own 40% (StatsBomb coords). Completed / attempted."
    ),
    "crosses": "Pass.cross=true. Completed / total.",
    "long_balls": "High Pass height or length ≥30 yards. Completed / total.",
    "through_balls": (
        "Pass.through_ball or technique Through Ball when the feed provides it "
        "(often 0 on open data)."
    ),
    "interceptions": "StatsBomb Interception events.",
    "recoveries": "StatsBomb Ball Recovery events.",
    "high_recoveries": "Ball recoveries with location in the attacking final third (x≥80).",
    "balls_lost": "Miscontrol + Dispossessed + Error events.",
    "blocks": "StatsBomb Block events (defensive blocks).",
    "clearances": "StatsBomb Clearance events.",
    "gk_saves": "Goal Keeper events with type Shot Saved (alias of saves).",
    "shots_faced": (
        "Goal Keeper events: Shot Faced + Shot Saved + Goal Conceded "
        "(+ penalty faced/saved variants)."
    ),
    "shots_on_target_faced": "Saves + goals conceded (on-target shots the keeper faced).",
    "goals_conceded": "Goal Keeper events with type Goal Conceded / Penalty Conceded.",
    "saves": "Goal Keeper events with type Shot Saved / Penalty Saved / Saved To Post.",
    "save_pct": "Saves / shots on target faced × 100.",
    "gk_passes": (
        "All Pass events by players who logged Goal Keeper actions "
        "(completed / attempted, with accuracy %)."
    ),
    "ground_duels": "Non-aerial Duel + 50/50 + Dribble. Won / total.",
    "aerial_duels": (
        "Aerial Lost duels plus aerial_won flags on pass/shot/clearance. Won / total."
    ),
    "ppda": (
        "Opponent SPADL passes with start_x < 60% of pitch length, divided by this team's "
        "tackles + interceptions + fouls in the same physical zone "
        "(start_x > 40% in this team's SPADL frame). Full match. Lower = more intense press."
    ),
}


def compute_match_stats(bundle: MatchBundle) -> dict[str, Any]:
    """Compute team and player stats for one loaded match."""
    actions = bundle.actions.copy()
    events = bundle.events.copy()
    teams = _team_lookup(bundle)
    home_id = int(bundle.game["home_team_id"])
    away_id = int(bundle.game["away_team_id"])

    team_rows = []
    player_rows = []
    for team_id, team_name in teams.items():
        team_actions = actions[actions["team_id"] == team_id]
        opp_actions = actions[actions["team_id"] != team_id]
        team_events = events[events["team_id"] == team_id]

        team_stats = _team_stats(team_id, team_name, team_actions, opp_actions, team_events, events)
        team_rows.append(team_stats)
        player_rows.extend(_player_stats(team_id, team_name, team_actions, team_events))

    return {
        "source": {
            "provider": "StatsBomb",
            "dataset": "open-data",
            "attribution": "Data provided by StatsBomb. See https://github.com/statsbomb/open-data",
            "schema": "SPADL via socceraction + StatsBomb event catalog",
        },
        "definitions": dict(CATALOG_DEFINITIONS),
        "match": {
            "game_id": bundle.game_id,
            "competition": bundle.game.get("competition_name"),
            "season": bundle.game.get("season_name"),
            "game_date": str(bundle.game.get("game_date")),
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team": teams.get(home_id),
            "away_team": teams.get(away_id),
            "home_score": _maybe_int(bundle.game.get("home_score")),
            "away_score": _maybe_int(bundle.game.get("away_score")),
        },
        "teams": team_rows,
        "players": player_rows,
    }


def _team_lookup(bundle: MatchBundle) -> dict[int, str]:
    return {
        int(r.team_id): str(r.team_name)
        for r in bundle.teams.drop_duplicates("team_id").itertuples(index=False)
    }


def _team_stats(
    team_id: int,
    team_name: str,
    team_actions: pd.DataFrame,
    opp_actions: pd.DataFrame,
    team_events: pd.DataFrame,
    all_events: pd.DataFrame,
) -> dict[str, Any]:
    catalog = team_event_catalog(team_events)
    xg = _sum_xg(team_events)
    possession_pct = _possession_pct(all_events, team_id)
    ppda = _ppda(team_actions, opp_actions)

    # Prefer event-stream shot/goal counts; fall back to SPADL if events lack shots.
    goals = catalog["goals_raw"]
    shots = catalog["shots_raw"]
    if shots == 0 and not team_actions.empty:
        spadl_shots = team_actions[team_actions["type_name"].isin(_SHOT_TYPES)]
        shots = int(len(spadl_shots))
        goals = int((spadl_shots["result_name"] == "success").sum())

    interceptions = catalog["interceptions_raw"]
    clearances = catalog["clearances_raw"]
    if interceptions == 0 and not team_actions.empty:
        interceptions = int((team_actions["type_name"] == "interception").sum())
    if clearances == 0 and not team_actions.empty:
        clearances = int((team_actions["type_name"] == "clearance").sum())

    # Legacy-friendly progressive (completed only) + new attempted.
    prog_completed = catalog["progressive_passes_completed"]
    prog_attempted = catalog["progressive_passes_attempted"]

    row = {
        "team_id": team_id,
        "team_name": team_name,
        # Summary
        "goals": goals,
        "possession_pct": possession_pct,
        "fouls_committed": catalog["fouls_committed"],
        "fouls_won": catalog["fouls_won"],
        "fouls": catalog["fouls_committed"],  # backward compat
        "yellow_cards": catalog["yellow_cards"],
        "red_cards": catalog["red_cards"],
        "offsides": catalog["offsides"],
        "corners": catalog["corners"],
        "free_kicks": catalog["free_kicks"],
        "goal_kicks": catalog["goal_kicks"],
        "throw_ins": catalog["throw_ins"],
        # Attack
        "xg": xg,
        "shots": shots,
        "shots_on_target": catalog["shots_on_target"],
        "shot_accuracy": catalog["shot_accuracy"],
        "blocked_shots": catalog["blocked_shots"],
        "missed_shots": catalog["missed_shots"],
        "shots_inside_box": catalog["shots_inside_box"],
        "shots_outside_box": catalog["shots_outside_box"],
        "headed_shots": catalog["headed_shots"],
        "key_passes": catalog["key_passes"],
        "into_final_third_completed": catalog["into_final_third_completed"],
        "into_final_third_attempted": catalog["into_final_third_attempted"],
        "into_box_completed": catalog["into_box_completed"],
        "into_box_attempted": catalog["into_box_attempted"],
        # Passes
        "passes_attempted": catalog["open_passes_attempted"],
        "passes_completed": catalog["open_passes_completed"],
        "pass_accuracy": catalog["open_pass_accuracy"],
        "progressive_passes": prog_completed,
        "progressive_passes_completed": prog_completed,
        "progressive_passes_attempted": prog_attempted,
        "crosses_completed": catalog["crosses_completed"],
        "crosses_total": catalog["crosses_total"],
        "long_balls_completed": catalog["long_balls_completed"],
        "long_balls_total": catalog["long_balls_total"],
        "through_balls_completed": catalog["through_balls_completed"],
        "through_balls_total": catalog["through_balls_total"],
        # Defence
        "interceptions": interceptions,
        "recoveries": catalog["recoveries"],
        "high_recoveries": catalog["high_recoveries"],
        "balls_lost": catalog["balls_lost"],
        "blocks": catalog["blocks"],
        "clearances": clearances,
        "gk_saves": catalog["gk_saves"],
        "shots_faced": catalog["shots_faced"],
        "shots_on_target_faced": catalog["shots_on_target_faced"],
        "goals_conceded": catalog["goals_conceded"],
        "saves": catalog["saves"],
        "save_pct": catalog["save_pct"],
        "gk_passes_attempted": catalog["gk_passes_attempted"],
        "gk_passes_completed": catalog["gk_passes_completed"],
        "gk_pass_accuracy": catalog["gk_pass_accuracy"],
        "tackles": int((team_actions["type_name"] == "tackle").sum()) if not team_actions.empty else 0,
        # Duels
        "ground_duels_won": catalog["ground_duels_won"],
        "ground_duels_total": catalog["ground_duels_total"],
        "aerials_won": catalog["aerials_won"],
        "aerials_lost": catalog["aerials_lost"],
        "aerials_total": catalog["aerials_total"],
        "ppda": ppda,
        "sections": _sections_view(
            goals=goals,
            possession_pct=possession_pct,
            catalog=catalog,
            xg=xg,
            shots=shots,
            prog_completed=prog_completed,
            prog_attempted=prog_attempted,
            interceptions=interceptions,
            clearances=clearances,
            ppda=ppda,
        ),
    }
    return row


def _sections_view(
    *,
    goals: int,
    possession_pct: float | None,
    catalog: dict[str, Any],
    xg: float,
    shots: int,
    prog_completed: int,
    prog_attempted: int,
    interceptions: int,
    clearances: int,
    ppda: float | None,
) -> dict[str, dict[str, Any]]:
    """Grouped view for UIs that want Match / Attack / Passes / Defence blocks."""
    return {
        "match": {
            "goals": goals,
            "possession_pct": possession_pct,
            "fouls_committed": catalog["fouls_committed"],
            "fouls_won": catalog["fouls_won"],
            "yellow_cards": catalog["yellow_cards"],
            "red_cards": catalog["red_cards"],
            "offsides": catalog["offsides"],
            "corners": catalog["corners"],
            "free_kicks": catalog["free_kicks"],
            "goal_kicks": catalog["goal_kicks"],
            "throw_ins": catalog["throw_ins"],
        },
        "attack": {
            "xg": xg,
            "shots": shots,
            "shots_on_target": catalog["shots_on_target"],
            "shot_accuracy": catalog["shot_accuracy"],
            "blocked_shots": catalog["blocked_shots"],
            "missed_shots": catalog["missed_shots"],
            "shots_inside_box": catalog["shots_inside_box"],
            "shots_outside_box": catalog["shots_outside_box"],
            "headed_shots": catalog["headed_shots"],
            "key_passes": catalog["key_passes"],
            "into_final_third_completed": catalog["into_final_third_completed"],
            "into_final_third_attempted": catalog["into_final_third_attempted"],
            "into_box_completed": catalog["into_box_completed"],
            "into_box_attempted": catalog["into_box_attempted"],
        },
        "passes": {
            "passes_attempted": catalog["open_passes_attempted"],
            "passes_completed": catalog["open_passes_completed"],
            "pass_accuracy": catalog["open_pass_accuracy"],
            "progressive_passes_completed": prog_completed,
            "progressive_passes_attempted": prog_attempted,
            "crosses_completed": catalog["crosses_completed"],
            "crosses_total": catalog["crosses_total"],
            "long_balls_completed": catalog["long_balls_completed"],
            "long_balls_total": catalog["long_balls_total"],
            "through_balls_completed": catalog["through_balls_completed"],
            "through_balls_total": catalog["through_balls_total"],
        },
        "defence": {
            "interceptions": interceptions,
            "recoveries": catalog["recoveries"],
            "high_recoveries": catalog["high_recoveries"],
            "balls_lost": catalog["balls_lost"],
            "blocks": catalog["blocks"],
            "clearances": clearances,
            "gk_saves": catalog["gk_saves"],
            "ground_duels_won": catalog["ground_duels_won"],
            "ground_duels_total": catalog["ground_duels_total"],
            "aerials_won": catalog["aerials_won"],
            "aerials_total": catalog["aerials_total"],
            "ppda": ppda,
        },
        "goalkeeper": {
            "shots_faced": catalog["shots_faced"],
            "shots_on_target_faced": catalog["shots_on_target_faced"],
            "goals_conceded": catalog["goals_conceded"],
            "saves": catalog["saves"],
            "save_pct": catalog["save_pct"],
            "gk_passes_attempted": catalog["gk_passes_attempted"],
            "gk_passes_completed": catalog["gk_passes_completed"],
            "gk_pass_accuracy": catalog["gk_pass_accuracy"],
        },
    }


def _player_stats(
    team_id: int,
    team_name: str,
    team_actions: pd.DataFrame,
    team_events: pd.DataFrame,
) -> list[dict[str, Any]]:
    if team_actions.empty and (team_events is None or team_events.empty):
        return []

    # Index players from events when available so GK-only contributors appear.
    player_ids: set[int] = set()
    if not team_actions.empty:
        for pid in team_actions["player_id"].dropna().unique():
            player_ids.add(int(pid))
    if team_events is not None and not team_events.empty and "player_id" in team_events.columns:
        for pid in team_events["player_id"].dropna().unique():
            player_ids.add(int(pid))

    rows = []
    for player_id in player_ids:
        pact = (
            team_actions[team_actions["player_id"] == player_id]
            if not team_actions.empty
            else team_actions
        )
        pev = (
            team_events[team_events["player_id"] == player_id]
            if team_events is not None and not team_events.empty
            else team_events
        )
        catalog = team_event_catalog(pev)
        name = None
        if not pact.empty and "player_name" in pact.columns and pact["player_name"].notna().any():
            name = pact["player_name"].dropna().iloc[0]
        elif pev is not None and not pev.empty and "player_name" in pev.columns:
            if pev["player_name"].notna().any():
                name = pev["player_name"].dropna().iloc[0]

        rows.append(
            {
                "player_id": int(player_id),
                "player_name": name,
                "team_id": team_id,
                "team_name": team_name,
                "xg": _sum_xg(pev) if pev is not None else 0.0,
                "goals": catalog["goals_raw"],
                "shots": catalog["shots_raw"],
                "shots_on_target": catalog["shots_on_target"],
                "key_passes": catalog["key_passes"],
                "passes_attempted": catalog["open_passes_attempted"],
                "passes_completed": catalog["open_passes_completed"],
                "pass_accuracy": catalog["open_pass_accuracy"],
                "progressive_passes": catalog["progressive_passes_completed"],
                "progressive_passes_completed": catalog["progressive_passes_completed"],
                "progressive_passes_attempted": catalog["progressive_passes_attempted"],
                "tackles": int((pact["type_name"] == "tackle").sum()) if not pact.empty else 0,
                "interceptions": catalog["interceptions_raw"],
                "clearances": catalog["clearances_raw"],
                "recoveries": catalog["recoveries"],
                "blocks": catalog["blocks"],
                "gk_saves": catalog["gk_saves"],
                "shots_faced": catalog["shots_faced"],
                "shots_on_target_faced": catalog["shots_on_target_faced"],
                "goals_conceded": catalog["goals_conceded"],
                "saves": catalog["saves"],
                "save_pct": catalog["save_pct"],
                "gk_passes_attempted": catalog["gk_passes_attempted"],
                "gk_passes_completed": catalog["gk_passes_completed"],
                "gk_pass_accuracy": catalog["gk_pass_accuracy"],
                "is_goalkeeper": bool(
                    catalog["shots_faced"]
                    or catalog["saves"]
                    or catalog["goals_conceded"]
                    or catalog["gk_passes_attempted"]
                ),
                "aerials_won": catalog["aerials_won"],
                "aerials_lost": catalog["aerials_lost"],
                "ground_duels_won": catalog["ground_duels_won"],
                "ground_duels_total": catalog["ground_duels_total"],
            }
        )
    rows.sort(key=lambda r: (-(r["xg"] or 0), -(r["passes_attempted"]), r["player_name"] or ""))
    return rows


_PASS_TYPES = {
    "pass",
    "cross",
    "throw_in",
    "freekick_crossed",
    "freekick_short",
    "corner_crossed",
    "corner_short",
    "goalkick",
}
_SHOT_TYPES = {"shot", "shot_penalty", "shot_freekick"}
_DEF_TYPES = {"tackle", "interception", "foul"}


def _progressive_passes(passes: pd.DataFrame) -> pd.DataFrame:
    if passes.empty:
        return passes
    ok = passes[passes["result_name"] == "success"].copy()
    if ok.empty:
        return ok
    advance = ok["end_x"] - ok["start_x"]
    into_box = ok["end_x"] >= PENALTY_BOX_X
    # Exclude passes originating in the defending 40% (FBref-style).
    not_from_own_40 = ok["start_x"] >= 0.4 * FIELD_LENGTH
    mask = ((advance >= PROGRESSIVE_YARDS_M) | into_box) & not_from_own_40
    return ok[mask]


def _ppda(team_actions: pd.DataFrame, opp_actions: pd.DataFrame) -> float | None:
    """PPDA for `team_actions`' team. See definitions in compute_match_stats output."""
    if team_actions.empty or opp_actions.empty:
        return None
    opp_passes = opp_actions[
        opp_actions["type_name"].isin(_PASS_TYPES) & (opp_actions["start_x"] < PPDA_OWN_ZONE_X)
    ]
    # Same physical zone in this team's LTR frame: opponent own-60% ↔ x > 40%.
    team_defs = team_actions[
        team_actions["type_name"].isin(_DEF_TYPES)
        & (team_actions["start_x"] > (FIELD_LENGTH - PPDA_OWN_ZONE_X))
    ]
    n_def = int(len(team_defs))
    if n_def == 0:
        return None
    return round(float(len(opp_passes)) / n_def, 3)


def _possession_pct(events: pd.DataFrame, team_id: int) -> float | None:
    """Duration share of StatsBomb possession chains."""
    if events.empty or "possession" not in events.columns or "possession_team_id" not in events.columns:
        return None

    df = events.sort_values(["period_id", "timestamp", "index"]).copy()
    # Build seconds from period + timestamp
    df["t"] = df.apply(_event_seconds, axis=1)
    durations: dict[int, float] = {}
    for _, chain in df.groupby(["period_id", "possession"], sort=False):
        tid = chain["possession_team_id"].dropna()
        if tid.empty:
            continue
        owner = int(tid.iloc[0])
        start = float(chain["t"].iloc[0])
        end = float(chain["t"].iloc[-1])
        # Cap chain length; if only one event, give a small epsilon
        dur = max(end - start, 0.5)
        durations[owner] = durations.get(owner, 0.0) + dur

    total = sum(durations.values())
    if total <= 0:
        return None
    return round(100.0 * durations.get(team_id, 0.0) / total, 1)


def _event_seconds(row: pd.Series) -> float:
    period = int(row["period_id"]) if pd.notna(row.get("period_id")) else 1
    base = (period - 1) * 45 * 60
    ts = row.get("timestamp")
    if pd.isna(ts):
        return float(base)
    if hasattr(ts, "total_seconds"):
        return float(base + ts.total_seconds())
    # "HH:MM:SS.mmm" or pandas Timedelta string
    try:
        parts = str(ts).split(":")
        if len(parts) == 3:
            h, m, s = parts
            return float(base + int(h) * 3600 + int(m) * 60 + float(s))
    except (TypeError, ValueError):
        pass
    if "time_seconds" in row and pd.notna(row["time_seconds"]):
        return float(base + row["time_seconds"])
    return float(base)


def _sum_xg(events: pd.DataFrame) -> float:
    """Sum StatsBomb xG from flattened columns or nested ``extra.shot.statsbomb_xg``."""
    if events is None or events.empty:
        return 0.0

    for candidate in ("shot_statsbomb_xg", "statsbomb_xg"):
        if candidate in events.columns:
            vals = pd.to_numeric(events[candidate], errors="coerce").fillna(0.0)
            total = float(vals.sum())
            if total > 0:
                return round(total, 3)

    total = 0.0
    shot_rows = events[events["type_name"] == "Shot"] if "type_name" in events.columns else events
    for _, row in shot_rows.iterrows():
        extra = row.get("extra")
        if not isinstance(extra, dict):
            continue
        shot = extra.get("shot")
        if isinstance(shot, dict) and shot.get("statsbomb_xg") is not None:
            total += float(shot["statsbomb_xg"])
    return round(total, 3)


def _aerials(events: pd.DataFrame) -> tuple[int, int]:
    """Backward-compatible wrapper around event_metrics aerials."""
    from statman.event_metrics import _aerials as _ev_aerials

    return _ev_aerials(events)


def _ratio(num: int, den: int) -> float | None:
    if den == 0:
        return None
    return round(100.0 * num / den, 1)


def _maybe_int(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
