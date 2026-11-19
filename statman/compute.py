"""Derive StatMan match stats from SPADL actions and raw StatsBomb events."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from statman.load import MatchBundle

FIELD_LENGTH = 105.0
FIELD_WIDTH = 68.0
# FBref-style progressive pass: ≥10 yards (~9.14 m) toward goal, or into the box.
PROGRESSIVE_YARDS_M = 10 * 0.9144
PENALTY_BOX_X = FIELD_LENGTH - 16.5
# PPDA zone: opponent passes in their own 60% of the pitch.
PPDA_OWN_ZONE_X = 0.6 * FIELD_LENGTH


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
            "schema": "SPADL via socceraction",
        },
        "definitions": {
            "progressive_pass": (
                "Completed pass that advances the ball at least 10 yards (9.14 m) toward "
                "the opponent goal, or any completed pass into the penalty area. "
                "Excludes incomplete passes."
            ),
            "ppda": (
                "Opponent passes with start_x < 60% of pitch length, divided by this team's "
                "tackles + interceptions + fouls in the same physical zone "
                "(start_x > 40% in this team's SPADL frame). Lower = more intense press."
            ),
            "possession_pct": "Share of StatsBomb possession-chain duration by team.",
            "xg": "Sum of StatsBomb shot.statsbomb_xg on raw shot events (open-data).",
            "aerials": (
                "Raw StatsBomb aerials before SPADL: losers are Duel/Aerial Lost; "
                "winners are pass/shot/clearance events with aerial_won=true."
            ),
            "pass_accuracy": "Successful SPADL passes / attempted SPADL passes "
            "(includes crosses, free kicks, corners, throw-ins).",
        },
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
    pass_mask = team_actions["type_name"].isin(_PASS_TYPES)
    passes = team_actions[pass_mask]
    pass_attempted = int(len(passes))
    pass_completed = int((passes["result_name"] == "success").sum())
    progressive = int(_progressive_passes(passes).shape[0])

    shots = team_actions[team_actions["type_name"].isin(_SHOT_TYPES)]
    goals = int((shots["result_name"] == "success").sum())

    xg = _sum_xg(team_events)
    aerials_won, aerials_lost = _aerials(team_events)
    possession_pct = _possession_pct(all_events, team_id)
    ppda = _ppda(team_actions, opp_actions)

    return {
        "team_id": team_id,
        "team_name": team_name,
        "possession_pct": possession_pct,
        "xg": xg,
        "goals": goals,
        "shots": int(len(shots)),
        "passes_attempted": pass_attempted,
        "passes_completed": pass_completed,
        "pass_accuracy": _ratio(pass_completed, pass_attempted),
        "progressive_passes": progressive,
        "tackles": int((team_actions["type_name"] == "tackle").sum()),
        "interceptions": int((team_actions["type_name"] == "interception").sum()),
        "clearances": int((team_actions["type_name"] == "clearance").sum()),
        "fouls": int((team_actions["type_name"] == "foul").sum()),
        "aerials_won": aerials_won,
        "aerials_lost": aerials_lost,
        "aerials_total": aerials_won + aerials_lost,
        "ppda": ppda,
    }


def _player_stats(
    team_id: int,
    team_name: str,
    team_actions: pd.DataFrame,
    team_events: pd.DataFrame,
) -> list[dict[str, Any]]:
    if team_actions.empty:
        return []

    rows = []
    for player_id, pact in team_actions.groupby("player_id"):
        if pd.isna(player_id):
            continue
        name = pact["player_name"].dropna().iloc[0] if pact["player_name"].notna().any() else None
        passes = pact[pact["type_name"].isin(_PASS_TYPES)]
        attempted = int(len(passes))
        completed = int((passes["result_name"] == "success").sum())
        shots = pact[pact["type_name"].isin(_SHOT_TYPES)]
        pev = team_events[team_events["player_id"] == player_id]
        aerials_won, aerials_lost = _aerials(pev)
        rows.append(
            {
                "player_id": int(player_id),
                "player_name": name,
                "team_id": team_id,
                "team_name": team_name,
                "xg": _sum_xg(pev),
                "goals": int((shots["result_name"] == "success").sum()),
                "shots": int(len(shots)),
                "passes_attempted": attempted,
                "passes_completed": completed,
                "pass_accuracy": _ratio(completed, attempted),
                "progressive_passes": int(_progressive_passes(passes).shape[0]),
                "tackles": int((pact["type_name"] == "tackle").sum()),
                "interceptions": int((pact["type_name"] == "interception").sum()),
                "clearances": int((pact["type_name"] == "clearance").sum()),
                "aerials_won": aerials_won,
                "aerials_lost": aerials_lost,
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
    if events.empty:
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
    """Count aerial duels from raw StatsBomb events (not available in SPADL).

    StatsBomb typically records the loser as a Duel with type ``Aerial Lost``,
    and marks the winner with ``aerial_won: true`` on the following pass/shot/clearance.
    """
    if events.empty or "type_name" not in events.columns:
        return 0, 0

    won = 0
    lost = 0
    for _, row in events.iterrows():
        extra = row.get("extra")
        if not isinstance(extra, dict):
            continue

        duel = extra.get("duel")
        if isinstance(duel, dict):
            duel_type = str(duel.get("type", {}).get("name", ""))
            if "aerial" in duel_type.lower():
                if "won" in duel_type.lower():
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


def _maybe_int(v: Any) -> int | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
