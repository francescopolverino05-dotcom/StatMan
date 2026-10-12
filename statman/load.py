"""Load one StatsBomb open-data match and convert it to SPADL."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import pandas as pd

warnings.filterwarnings(
    action="ignore",
    message="credentials were not supplied. open data access only",
)

# Belgium 2–0 England, FIFA World Cup 2018 third-place play-off.
# Same demo match used in socceraction's public notebooks.
DEFAULT_GAME_ID = 8657
DEFAULT_COMPETITION_ID = 43  # FIFA World Cup
DEFAULT_SEASON_ID = 3  # 2018


@dataclass
class MatchBundle:
    """Raw StatsBomb frames plus SPADL actions for one match."""

    game_id: int
    game: dict[str, Any]
    teams: pd.DataFrame
    players: pd.DataFrame
    events: pd.DataFrame
    actions: pd.DataFrame


def load_match(game_id: int = DEFAULT_GAME_ID) -> MatchBundle:
    """Fetch one open-data match and convert events to SPADL."""
    from socceraction.data.statsbomb import StatsBombLoader
    import socceraction.spadl as spadl

    loader = StatsBombLoader(getter="remote", creds={"user": None, "passwd": None})

    game_row = _find_game(loader, game_id)
    teams = loader.teams(game_id)
    players = loader.players(game_id)
    events = loader.events(game_id)
    actions = spadl.statsbomb.convert_to_actions(
        events,
        home_team_id=int(game_row["home_team_id"]),
        xy_fidelity_version=1,
        shot_fidelity_version=1,
    )
    actions = (
        actions.merge(spadl.actiontypes_df(), how="left")
        .merge(spadl.results_df(), how="left")
        .merge(spadl.bodyparts_df(), how="left")
        .merge(
            players[["player_id", "player_name", "nickname"]].drop_duplicates("player_id"),
            how="left",
            on="player_id",
        )
        .merge(teams[["team_id", "team_name"]].drop_duplicates("team_id"), how="left", on="team_id")
    )
    actions["player_name"] = actions.apply(
        lambda r: r["nickname"] if pd.notna(r.get("nickname")) and r["nickname"] else r["player_name"],
        axis=1,
    )

    return MatchBundle(
        game_id=game_id,
        game=game_row,
        teams=teams,
        players=players,
        events=events,
        actions=actions,
    )


def _find_game(loader: Any, game_id: int) -> dict[str, Any]:
    """Locate match metadata across open competitions."""
    competitions = loader.competitions()
    # Prefer the known World Cup 2018 season first for the default match.
    preferred = competitions[
        (competitions["competition_id"] == DEFAULT_COMPETITION_ID)
        & (competitions["season_id"] == DEFAULT_SEASON_ID)
    ]
    search_order = pd.concat([preferred, competitions]).drop_duplicates(
        subset=["competition_id", "season_id"]
    )

    for row in search_order.itertuples(index=False):
        games = loader.games(int(row.competition_id), int(row.season_id))
        hit = games[games["game_id"] == game_id]
        if not hit.empty:
            g = hit.iloc[0].to_dict()
            g["competition_id"] = int(row.competition_id)
            g["season_id"] = int(row.season_id)
            g["competition_name"] = getattr(row, "competition_name", None)
            g["season_name"] = getattr(row, "season_name", None)
            return g

    raise ValueError(
        f"game_id={game_id} was not found in StatsBomb open data. "
        "Try the default Belgium–England World Cup 2018 match (8657)."
    )


def list_demo_games(limit: int = 20) -> list[dict[str, Any]]:
    """Return open World Cup 2018 games for the UI.

    Always pins the default Belgium–England third-place match first so the
    demo CTA and docs stay aligned with ``DEFAULT_GAME_ID``.
    """
    from socceraction.data.statsbomb import StatsBombLoader

    loader = StatsBombLoader(getter="remote", creds={"user": None, "passwd": None})
    games = loader.games(DEFAULT_COMPETITION_ID, DEFAULT_SEASON_ID)

    def _row_to_game(row: Any) -> dict[str, Any]:
        return {
            "game_id": int(row.game_id),
            "game_date": str(row.game_date),
            "home_team_id": int(row.home_team_id),
            "away_team_id": int(row.away_team_id),
            "home_score": int(row.home_score) if pd.notna(row.home_score) else None,
            "away_score": int(row.away_score) if pd.notna(row.away_score) else None,
            "competition": "FIFA World Cup",
            "season": "2018",
        }

    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    # Pin the documented demo match first when it exists in this season.
    default_hit = games[games["game_id"] == DEFAULT_GAME_ID]
    if not default_hit.empty:
        pinned = _row_to_game(default_hit.iloc[0])
        out.append(pinned)
        seen.add(pinned["game_id"])

    for row in games.sort_values("game_date").itertuples(index=False):
        game_id = int(row.game_id)
        if game_id in seen:
            continue
        out.append(_row_to_game(row))
        seen.add(game_id)
        if len(out) >= limit:
            break

    # Attach team names; always resolve names for the pinned demo match.
    if out:
        name_map: dict[int, str] = {}
        scan_ids = [out[0]["game_id"]] + [g["game_id"] for g in out[1:16]]
        for gid in dict.fromkeys(scan_ids):
            tdf = loader.teams(gid)
            for r in tdf.itertuples(index=False):
                name_map[int(r.team_id)] = str(r.team_name)
        for g in out:
            g["home_team"] = name_map.get(g["home_team_id"], str(g["home_team_id"]))
            g["away_team"] = name_map.get(g["away_team_id"], str(g["away_team_id"]))

    return out
