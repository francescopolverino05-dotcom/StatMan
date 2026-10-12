"""Pitch maps from SPADL / StatsBomb coordinates via mplsoccer."""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from mplsoccer import Pitch  # noqa: E402

from statman.compute import (
    FIELD_LENGTH,
    FIELD_WIDTH,
    _PASS_TYPES,
    _SHOT_TYPES,
    _progressive_passes,
)
from statman.load import MatchBundle, load_match

MapKind = Literal["shots", "progressive", "defence"]

# StatsBomb open pitch → SPADL metres.
_SB_LENGTH = 120.0
_SB_WIDTH = 80.0

_HOME_COLOR = "#1f6b3a"
_AWAY_COLOR = "#c45c26"
_GOAL_EDGE = "#0f3d22"
_INK = "#142018"


def extract_map_events(bundle: MatchBundle) -> dict[str, Any]:
    """Pull plottable events (shots+xG, progressive passes, tackles/ints)."""

    actions = bundle.actions
    events = bundle.events
    home_id = int(bundle.game["home_team_id"])
    teams = {
        int(r.team_id): str(r.team_name)
        for r in bundle.teams.drop_duplicates("team_id").itertuples(index=False)
    }

    shots = _extract_shots(events, actions, home_id=home_id, teams=teams)
    progressive = _extract_progressive(actions, home_id=home_id, teams=teams)
    defence = _extract_defence(actions, home_id=home_id, teams=teams)

    return {
        "pitch": {
            "length": FIELD_LENGTH,
            "width": FIELD_WIDTH,
            "units": "metres",
            "orientation": "home_attacks_right",
        },
        "match": {
            "game_id": bundle.game_id,
            "home_team_id": home_id,
            "away_team_id": int(bundle.game["away_team_id"]),
            "home_team": teams.get(home_id),
            "away_team": teams.get(int(bundle.game["away_team_id"])),
        },
        "shots": shots,
        "progressive_passes": progressive,
        "defence": defence,
    }


def map_events_for_game(game_id: int) -> dict[str, Any]:
    return extract_map_events(load_match(game_id))


def render_map_png(
    game_id: int,
    kind: MapKind,
    *,
    team_id: int | None = None,
) -> bytes:
    """Render one pitch map PNG for a match (optionally one team)."""

    events = _cached_map_events(game_id)
    title_bits = {
        "shots": "Shot map (marker size ∝ xG)",
        "progressive": "Progressive passes",
        "defence": "Tackles & interceptions",
    }
    match = events["match"]
    home_name = match["home_team"] or "Home"
    away_name = match["away_team"] or "Away"

    if kind == "shots":
        fig = _fig_shots(events["shots"], team_id=team_id, home_name=home_name, away_name=away_name)
    elif kind == "progressive":
        fig = _fig_progressive(
            events["progressive_passes"],
            team_id=team_id,
            home_name=home_name,
            away_name=away_name,
        )
    elif kind == "defence":
        fig = _fig_defence(events["defence"], team_id=team_id, home_name=home_name, away_name=away_name)
    else:
        raise ValueError(f"Unknown map kind: {kind}")

    fig.suptitle(
        f"{home_name} vs {away_name} — {title_bits[kind]}",
        fontsize=13,
        fontweight="bold",
        color=_INK,
        y=0.98,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="#f3f7f2")
    plt.close(fig)
    return buf.getvalue()


@lru_cache(maxsize=16)
def _cached_map_events(game_id: int) -> dict[str, Any]:
    return map_events_for_game(game_id)


def _extract_shots(
    events: pd.DataFrame,
    actions: pd.DataFrame,
    *,
    home_id: int,
    teams: dict[int, str],
) -> list[dict[str, Any]]:
    """Shots from StatsBomb events (native xG) with SPADL-metre locations."""

    if events.empty or "type_name" not in events.columns:
        return _shots_from_actions(actions, home_id=home_id, teams=teams)

    out: list[dict[str, Any]] = []
    shots = events[events["type_name"] == "Shot"]
    for _, row in shots.iterrows():
        loc = row.get("location")
        if not isinstance(loc, (list, tuple)) or len(loc) < 2:
            continue
        x_sb, y_sb = float(loc[0]), float(loc[1])
        x, y = _sb_to_spadl(x_sb, y_sb)
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        shot = extra.get("shot") if isinstance(extra.get("shot"), dict) else {}
        xg = float(shot.get("statsbomb_xg") or 0.0)
        outcome = ""
        if isinstance(shot.get("outcome"), dict):
            outcome = str(shot["outcome"].get("name") or "")
        is_goal = outcome.lower() == "goal" or bool(row.get("is_goal"))
        team_id = int(row["team_id"]) if pd.notna(row.get("team_id")) else None
        if team_id is None:
            continue
        player_id = int(row["player_id"]) if pd.notna(row.get("player_id")) else None
        # Prefer nickname/name from SPADL actions when available
        player_name = None
        if player_id is not None and not actions.empty:
            hit = actions[actions["player_id"] == player_id]["player_name"].dropna()
            if not hit.empty:
                player_name = str(hit.iloc[0])
        out.append(
            {
                "team_id": team_id,
                "team_name": teams.get(team_id, str(team_id)),
                "is_home": team_id == home_id,
                "player_id": player_id,
                "player_name": player_name,
                "x": round(x, 3),
                "y": round(y, 3),
                "xg": round(xg, 4),
                "is_goal": is_goal,
                "outcome": outcome or None,
            }
        )
    return out


def _shots_from_actions(
    actions: pd.DataFrame,
    *,
    home_id: int,
    teams: dict[int, str],
) -> list[dict[str, Any]]:
    shots = actions[actions["type_name"].isin(_SHOT_TYPES)]
    out = []
    for _, row in shots.iterrows():
        team_id = int(row["team_id"])
        out.append(
            {
                "team_id": team_id,
                "team_name": teams.get(team_id, str(team_id)),
                "is_home": team_id == home_id,
                "player_id": int(row["player_id"]) if pd.notna(row.get("player_id")) else None,
                "player_name": row.get("player_name"),
                "x": round(float(row["start_x"]), 3),
                "y": round(float(row["start_y"]), 3),
                "xg": None,
                "is_goal": row.get("result_name") == "success",
                "outcome": row.get("result_name"),
            }
        )
    return out


def _extract_progressive(
    actions: pd.DataFrame,
    *,
    home_id: int,
    teams: dict[int, str],
) -> list[dict[str, Any]]:
    passes = actions[actions["type_name"].isin(_PASS_TYPES)]
    prog = _progressive_passes(passes)
    out = []
    for _, row in prog.iterrows():
        team_id = int(row["team_id"])
        out.append(
            {
                "team_id": team_id,
                "team_name": teams.get(team_id, str(team_id)),
                "is_home": team_id == home_id,
                "player_id": int(row["player_id"]) if pd.notna(row.get("player_id")) else None,
                "player_name": row.get("player_name"),
                "x": round(float(row["start_x"]), 3),
                "y": round(float(row["start_y"]), 3),
                "end_x": round(float(row["end_x"]), 3),
                "end_y": round(float(row["end_y"]), 3),
            }
        )
    return out


def _extract_defence(
    actions: pd.DataFrame,
    *,
    home_id: int,
    teams: dict[int, str],
) -> list[dict[str, Any]]:
    defs = actions[actions["type_name"].isin({"tackle", "interception"})]
    out = []
    for _, row in defs.iterrows():
        team_id = int(row["team_id"])
        out.append(
            {
                "team_id": team_id,
                "team_name": teams.get(team_id, str(team_id)),
                "is_home": team_id == home_id,
                "player_id": int(row["player_id"]) if pd.notna(row.get("player_id")) else None,
                "player_name": row.get("player_name"),
                "type": str(row["type_name"]),
                "x": round(float(row["start_x"]), 3),
                "y": round(float(row["start_y"]), 3),
                "successful": row.get("result_name") == "success",
            }
        )
    return out


def _sb_to_spadl(x: float, y: float) -> tuple[float, float]:
    return x / _SB_LENGTH * FIELD_LENGTH, y / _SB_WIDTH * FIELD_WIDTH


def _pitch() -> Pitch:
    return Pitch(
        pitch_type="custom",
        pitch_length=FIELD_LENGTH,
        pitch_width=FIELD_WIDTH,
        line_color="#3d4a40",
        pitch_color="#e4eee3",
        linewidth=1.1,
        goal_type="box",
        corner_arcs=True,
    )


def _filter_team(rows: list[dict[str, Any]], team_id: int | None) -> list[dict[str, Any]]:
    if team_id is None:
        return rows
    return [r for r in rows if int(r["team_id"]) == int(team_id)]


def _color(row: dict[str, Any]) -> str:
    return _HOME_COLOR if row.get("is_home") else _AWAY_COLOR


def _fig_shots(
    shots: list[dict[str, Any]],
    *,
    team_id: int | None,
    home_name: str,
    away_name: str,
):
    rows = _filter_team(shots, team_id)
    pitch = _pitch()
    fig, ax = pitch.draw(figsize=(10.5, 7.2))
    for row in rows:
        xg = float(row["xg"] or 0.05)
        size = 80 + 900 * min(max(xg, 0.01), 0.8)
        face = _GOAL_EDGE if row.get("is_goal") else _color(row)
        edge = _GOAL_EDGE if row.get("is_goal") else "white"
        ax.scatter(
            row["x"],
            row["y"],
            s=size,
            c=face,
            edgecolors=edge,
            linewidths=1.2,
            alpha=0.85 if row.get("is_goal") else 0.7,
            zorder=3,
        )
    _legend_teams(ax, home_name, away_name, team_id)
    ax.text(
        0.01,
        -0.04,
        "Filled dark ring = goal · marker area scales with StatsBomb xG",
        transform=ax.transAxes,
        fontsize=8,
        color="#3d4a40",
    )
    return fig


def _fig_progressive(
    passes: list[dict[str, Any]],
    *,
    team_id: int | None,
    home_name: str,
    away_name: str,
):
    rows = _filter_team(passes, team_id)
    pitch = _pitch()
    fig, ax = pitch.draw(figsize=(10.5, 7.2))
    for row in rows:
        color = _color(row)
        pitch.arrows(
            row["x"],
            row["y"],
            row["end_x"],
            row["end_y"],
            ax=ax,
            color=color,
            width=1.2,
            headwidth=4,
            headlength=4,
            alpha=0.55,
        )
    _legend_teams(ax, home_name, away_name, team_id)
    return fig


def _fig_defence(
    defence: list[dict[str, Any]],
    *,
    team_id: int | None,
    home_name: str,
    away_name: str,
):
    rows = _filter_team(defence, team_id)
    pitch = _pitch()
    fig, ax = pitch.draw(figsize=(10.5, 7.2))
    for row in rows:
        marker = "s" if row.get("type") == "tackle" else "D"
        ax.scatter(
            row["x"],
            row["y"],
            s=55,
            c=_color(row),
            marker=marker,
            edgecolors="white",
            linewidths=0.8,
            alpha=0.8,
            zorder=3,
        )
    _legend_teams(ax, home_name, away_name, team_id)
    ax.text(
        0.01,
        -0.04,
        "Square = tackle · Diamond = interception",
        transform=ax.transAxes,
        fontsize=8,
        color="#3d4a40",
    )
    return fig


def _legend_teams(ax, home_name: str, away_name: str, team_id: int | None) -> None:
    if team_id is not None:
        return
    ax.scatter([], [], c=_HOME_COLOR, s=60, label=home_name)
    ax.scatter([], [], c=_AWAY_COLOR, s=60, label=away_name)
    ax.legend(loc="upper center", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.5, 1.08))
