"""EnjoyStats Streamlit dashboard — three-pillar view plus 2D pitch map.

Launch from the repository root::

    streamlit run app/dashboard.py
"""

from __future__ import annotations

import asyncio
import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
import streamlit as st
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Ellipse, Rectangle

from app.client import DEFAULT_BASE_URL, ProfileLoad, fetch_player_profile
from app.dummy_data import PitchAction, catalog
from app.metrics import PassDirections
from config.pitch_config import (
    CENTRE_CIRCLE_RADIUS_M,
    FIFA_PITCH,
    NORMALIZED_MAX,
    NORMALIZED_MIN,
    PENALTY_SPOT_DISTANCE_M,
    PitchDimensions,
)
from data_models.player_stats import AttemptSplit, PlayerMatchProfile

FetchFn = Callable[[str, UUID, UUID], ProfileLoad]

FIELD_GREEN = "#2e7d32"
FIELD_EDGE = "#145214"
LINE_COLOR = "#f8fafc"
LINEWIDTH = 1.7
PASS_SUCCESS_COLOR = "#90caf9"
PASS_FAILED_COLOR = "#ef9a9a"
GOAL_COLOR = "#76ff03"
ON_TARGET_COLOR = "#ffd54f"
MISSED_COLOR = "#ff1744"
BLOCKED_COLOR = "#b0bec5"


def has_valid_pitch_point(x: float | None, y: float | None) -> bool:
    """Return whether ``(x, y)`` is a finite point on the closed 0–100 grid."""

    if x is None or y is None:
        return False
    try:
        xf = float(x)
        yf = float(y)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(xf) or not math.isfinite(yf):
        return False
    return NORMALIZED_MIN <= xf <= NORMALIZED_MAX and NORMALIZED_MIN <= yf <= NORMALIZED_MAX


def draw_football_pitch(
    ax: Axes | None = None,
    *,
    pitch: PitchDimensions = FIFA_PITCH,
) -> tuple[Figure, Axes]:
    """Draw a FIFA pitch on the normalized 0–100 tagging grid.

    Touchlines, the halfway line, and both 18-yard penalty boxes are mapped
    from :data:`~config.pitch_config.FIFA_PITCH` so scatter points share the
    same coordinate system as live tagged events.

    Args:
        ax: Optional existing axes. When omitted a new figure is created.
        pitch: Physical pitch whose 0–100 projection is drawn.

    Returns:
        The matplotlib ``(figure, axes)`` pair. X is attacking length
        (own goal = 0, opponent = 100); Y is width (left touchline = 0).
    """

    sns.set_theme(style="white", rc={"axes.grid": False, "figure.facecolor": FIELD_EDGE})
    if ax is None:
        fig, ax = plt.subplots(figsize=(12.0, 7.8), dpi=120)
    else:
        fig = ax.figure

    ax.set_xlim(NORMALIZED_MIN, NORMALIZED_MAX)
    ax.set_ylim(NORMALIZED_MIN, NORMALIZED_MAX)
    ax.set_aspect(pitch.width_m / pitch.length_m)
    ax.set_facecolor(FIELD_GREEN)
    fig.patch.set_facecolor(FIELD_EDGE)
    ax.set_xlabel("Attacking length  ·  0 = own goal, 100 = opponent")
    ax.set_ylabel("Width  ·  0 = left touchline, 100 = right")
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.tick_params(colors="#d1fae5", labelsize=8)
    ax.xaxis.label.set_color("#d1fae5")
    ax.yaxis.label.set_color("#d1fae5")
    for spine in ax.spines.values():
        spine.set_color(LINE_COLOR)
        spine.set_linewidth(LINEWIDTH)

    span = NORMALIZED_MAX - NORMALIZED_MIN
    ax.add_patch(
        Rectangle(
            (NORMALIZED_MIN, NORMALIZED_MIN),
            span,
            span,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=LINEWIDTH,
            zorder=2,
        )
    )
    ax.plot(
        [50.0, 50.0],
        [NORMALIZED_MIN, NORMALIZED_MAX],
        color=LINE_COLOR,
        linewidth=LINEWIDTH,
        solid_capstyle="butt",
        zorder=2,
    )

    centre_rx = (CENTRE_CIRCLE_RADIUS_M / pitch.length_m) * span
    centre_ry = (CENTRE_CIRCLE_RADIUS_M / pitch.width_m) * span
    ax.add_patch(
        Ellipse(
            (50.0, 50.0),
            width=2.0 * centre_rx,
            height=2.0 * centre_ry,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=LINEWIDTH,
            zorder=2,
        )
    )
    ax.scatter([50.0], [50.0], s=16, color=LINE_COLOR, zorder=3)

    box_y_min = pitch.penalty_area_y_min_norm
    box_height = pitch.penalty_area_y_max_norm - box_y_min
    box_depth = pitch.penalty_area_depth_norm
    ax.add_patch(
        Rectangle(
            (NORMALIZED_MIN, box_y_min),
            box_depth,
            box_height,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=LINEWIDTH,
            zorder=2,
        )
    )
    ax.add_patch(
        Rectangle(
            (pitch.attacking_penalty_x_min_norm, box_y_min),
            box_depth,
            box_height,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=LINEWIDTH,
            zorder=2,
        )
    )

    goal_area_depth = (pitch.goal_area_depth_m / pitch.length_m) * span
    goal_area_y_min = ((pitch.width_m - pitch.goal_area_width_m) / (2.0 * pitch.width_m)) * span
    goal_area_height = span - (2.0 * goal_area_y_min)
    ax.add_patch(
        Rectangle(
            (NORMALIZED_MIN, goal_area_y_min),
            goal_area_depth,
            goal_area_height,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=1.2,
            zorder=2,
        )
    )
    ax.add_patch(
        Rectangle(
            (NORMALIZED_MAX - goal_area_depth, goal_area_y_min),
            goal_area_depth,
            goal_area_height,
            fill=False,
            edgecolor=LINE_COLOR,
            linewidth=1.2,
            zorder=2,
        )
    )

    spot_x = (PENALTY_SPOT_DISTANCE_M / pitch.length_m) * span
    ax.scatter(
        [spot_x, NORMALIZED_MAX - spot_x],
        [50.0, 50.0],
        s=16,
        color=LINE_COLOR,
        zorder=3,
    )
    return fig, ax


def _action_kind(action: PitchAction) -> str:
    return action.event_type.strip().lower()


def _is_goal(action: PitchAction) -> bool:
    if action.is_goal:
        return True
    outcome = (action.shot_outcome or "").strip().lower()
    return _action_kind(action) == "goal" or outcome == "goal"


def _shot_category(action: PitchAction) -> str:
    if _is_goal(action):
        return "goal"
    outcome = (action.shot_outcome or "").strip().lower()
    if outcome == "missed" or (outcome == "" and not action.successful):
        return "missed"
    if outcome == "blocked":
        return "blocked"
    if outcome == "on_target" or action.successful:
        return "on_target"
    return "missed"


def scatter_match_actions(
    ax: Axes,
    actions: Sequence[PitchAction],
) -> tuple[int, int]:
    """Plot shot and pass locations, skipping incomplete coordinates.

    Successful goals are green circles; missed shots are red X markers.
    Completed passes are light-blue circles with arrows to the end point
    when both end coordinates are valid.

    Args:
        ax: Pitch axes produced by :func:`draw_football_pitch`.
        actions: Tagged locations for the selected player.

    Returns:
        ``(plotted, skipped)`` counts. ``skipped`` includes tags whose start
        point is missing, non-finite, or outside the 0–100 grid.
    """

    plotted = 0
    skipped = 0
    buckets: dict[str, list[tuple[float, float]]] = {
        "goal": [],
        "on_target": [],
        "missed": [],
        "blocked": [],
        "pass_ok": [],
        "pass_fail": [],
    }
    arrows: list[tuple[float, float, float, float, str]] = []

    for action in actions:
        kind = _action_kind(action)
        if not has_valid_pitch_point(action.x, action.y):
            skipped += 1
            continue
        x = float(action.x)
        y = float(action.y)
        if kind in {"shot", "goal"}:
            buckets[_shot_category(action)].append((x, y))
            plotted += 1
            continue
        if kind in {"pass", "cross", "cutback", "assist"}:
            bucket = "pass_ok" if action.successful else "pass_fail"
            buckets[bucket].append((x, y))
            plotted += 1
            if has_valid_pitch_point(action.end_x, action.end_y):
                color = PASS_SUCCESS_COLOR if action.successful else PASS_FAILED_COLOR
                arrows.append((x, y, float(action.end_x), float(action.end_y), color))
            continue
        skipped += 1

    styles: tuple[tuple[str, str, str, str, float], ...] = (
        ("pass_ok", PASS_SUCCESS_COLOR, "o", "Completed pass", 70.0),
        ("pass_fail", PASS_FAILED_COLOR, "o", "Incomplete pass", 70.0),
        ("on_target", ON_TARGET_COLOR, "o", "Shot on target", 90.0),
        ("blocked", BLOCKED_COLOR, "D", "Blocked shot", 70.0),
        ("missed", MISSED_COLOR, "x", "Missed shot", 110.0),
        ("goal", GOAL_COLOR, "o", "GOAL", 150.0),
    )
    for key, color, marker, label, size in styles:
        points = buckets[key]
        if not points:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        sns.scatterplot(
            x=xs,
            y=ys,
            ax=ax,
            color=color,
            marker=marker,
            s=size,
            legend=False,
            zorder=5 if key in {"goal", "missed"} else 4,
            edgecolor="white" if marker in {"o", "D"} else None,
            linewidth=0.9 if marker in {"o", "D"} else 1.6,
            label=label,
        )

    for start_x, start_y, end_x, end_y, color in arrows:
        ax.annotate(
            "",
            xy=(end_x, end_y),
            xytext=(start_x, start_y),
            arrowprops={
                "arrowstyle": "-|>",
                "color": color,
                "lw": 1.2,
                "mutation_scale": 10,
            },
            zorder=3,
        )

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        legend = ax.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.08),
            ncol=min(len(labels), 4),
            frameon=True,
            fontsize=8,
        )
        legend.get_frame().set_facecolor("#145214")
        legend.get_frame().set_edgecolor(LINE_COLOR)
        for text in legend.get_texts():
            text.set_color(LINE_COLOR)
    return plotted, skipped


def _run_fetch(base_url: str, match_id: UUID, player_id: UUID) -> ProfileLoad:
    """Bridge Streamlit's sync runtime to the async FastAPI client."""

    return asyncio.run(fetch_player_profile(base_url, match_id, player_id))


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
          .block-container { padding-top: 1.4rem; max-width: 1280px; }
          div[data-testid="stMetric"] {
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 14px;
            padding: 0.75rem 0.9rem;
          }
          div[data-testid="stMetric"] label { color: #94a3b8; }
          div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: #f8fafc;
            font-weight: 700;
          }
          h1, h2, h3 { letter-spacing: -0.02em; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _match_options() -> dict[str, UUID]:
    options: dict[str, UUID] = {}
    for row in catalog():
        label = f"{row['match_label']}  ·  {row['match_id']}"
        options[label] = row["match_id"]  # type: ignore[assignment]
    return options


def _player_options(match_id: UUID) -> dict[str, UUID]:
    options: dict[str, UUID] = {}
    for row in catalog():
        if row["match_id"] != match_id:
            continue
        label = f"{row['player_label']}  ·  {row['player_id']}"
        options[label] = row["player_id"]  # type: ignore[assignment]
    return options


def _pct(value: float) -> str:
    return f"{value:.0%}"


def _split_rows(*pairs: tuple[str, AttemptSplit]) -> list[dict[str, object]]:
    return [
        {
            "Stat": label,
            "Success": split.success,
            "Total": split.total,
            "Accuracy": _pct(split.success_rate),
        }
        for label, split in pairs
    ]


def render_offensive(profile: PlayerMatchProfile) -> None:
    """Finishing, set pieces, and shot geography."""

    st.subheader("Offensive")
    st.caption("Goals, chance creation, shooting, and restarts.")
    offensive = profile.offensive
    identity = st.columns(2)
    identity[0].metric("Minutes played", f"{offensive.minutes:.1f}")
    identity[1].metric(
        "Number / name",
        f"#{profile.jersey_number or '—'} {profile.player_name or profile.position or 'Player'}",
    )
    top = st.columns(2)
    top[0].metric("Goals", offensive.goals)
    top[1].metric("Assists", offensive.assists)
    shots = st.columns(2)
    shots[0].metric("Total shots", offensive.total_shots)
    shots[1].metric("Shots on target", offensive.shots_on_target)
    more = st.columns(2)
    more[0].metric("Shooting accuracy", _pct(offensive.shot_accuracy))
    more[1].metric(
        "Inside / outside PA",
        f"{offensive.shots_inside_penalty_area} / {offensive.shots_outside_penalty_area}",
    )
    rest = st.columns(2)
    rest[0].metric("Shots blocked", offensive.blocked_shots)
    rest[1].metric("Shots missed", offensive.missed_shots)
    set_pieces = st.columns(2)
    set_pieces[0].metric("Offsides", offensive.offsides)
    set_pieces[1].metric("Penalty kicks", offensive.penalty_kicks)
    restarts = st.columns(3)
    restarts[0].metric("Freekicks", offensive.freekicks)
    restarts[1].metric("Corners", offensive.corners)
    restarts[2].metric("Throw-ins", offensive.throw_ins)


def render_defensive(profile: PlayerMatchProfile) -> None:
    """Duels, recoveries, cards, and pressing."""

    st.subheader("Defensive")
    st.caption("Duels, recoveries, turnovers, cards, and pressing intensity.")
    defensive = profile.defensive
    ground = defensive.ground_duels
    aerial = defensive.aerial_duels
    c1, c2 = st.columns(2)
    c1.metric("Ground duel win %", _pct(ground.success_rate), f"{ground.success}/{ground.total}")
    c2.metric("Aerial duel win %", _pct(aerial.success_rate), f"{aerial.success}/{aerial.total}")
    c1.progress(ground.success_rate)
    c2.progress(aerial.success_rate)
    cards = st.columns(3)
    cards[0].metric("Yellow cards", defensive.yellow_cards)
    cards[1].metric("Red cards", defensive.red_cards)
    cards[2].metric("Goals against", defensive.goals_against)
    press = st.columns(2)
    press[0].metric("PPDA", f"{defensive.ppda:.1f}")
    intercepts = defensive.interceptions
    press[1].metric(
        "Interceptions",
        intercepts.total,
        f"{intercepts.defensive_third}/{intercepts.middle_third}/{intercepts.final_third}",
    )
    fouls = st.columns(2)
    fouls[0].metric("Fouls", defensive.fouls.committed)
    fouls[1].metric("Fouls won", defensive.fouls.won)
    blocks = defensive.blocks
    st.markdown("**Blocks**")
    st.dataframe(
        [
            {"Type": "Shots", "Blocks": blocks.shots},
            {"Type": "Crosses", "Blocks": blocks.crosses},
            {"Type": "Passes", "Blocks": blocks.passes},
            {"Type": "Total", "Blocks": blocks.total},
        ],
        hide_index=True,
        width="stretch",
    )
    recoveries = defensive.ball_recoveries
    lost = defensive.ball_lost
    st.markdown("**Recoveries and balls lost by third**")
    st.dataframe(
        [
            {
                "Third": "Defensive",
                "Recoveries": recoveries.defensive_third,
                "Ball lost": lost.defensive_third,
            },
            {
                "Third": "Middle",
                "Recoveries": recoveries.middle_third,
                "Ball lost": lost.middle_third,
            },
            {
                "Third": "Final",
                "Recoveries": recoveries.final_third,
                "Ball lost": lost.final_third,
            },
        ],
        hide_index=True,
        width="stretch",
    )


def render_distribution(profile: PlayerMatchProfile, directions: PassDirections) -> None:
    """Pass accuracy, thirds, length, direction, and chance creation."""

    st.subheader("Distribution")
    st.caption("Passing by third, length, direction, and destination.")
    dist = profile.distribution
    passing = dist.passes
    st.metric(
        "Pass accuracy",
        _pct(passing.success_rate),
        f"{passing.success}/{passing.total} completed",
    )
    st.markdown("**Passes by tactical third**")
    st.dataframe(
        _split_rows(
            ("Defensive third", dist.pass_thirds.defensive_third),
            ("Middle third", dist.pass_thirds.middle_third),
            ("Final third", dist.pass_thirds.final_third),
            ("Into final third", dist.into_final_third),
            ("Into PA", dist.pass_locations.into_penalty_area),
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Pass length**")
    st.dataframe(
        _split_rows(
            ("Short", dist.pass_locations.short),
            ("Medium", dist.pass_locations.medium),
            ("Long", dist.pass_locations.long),
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown("**Direction of distribution**")
    d1, d2, d3 = st.columns(3)
    d1.metric(
        "Forward",
        (
            f"{dist.pass_directions.forward.success}/{dist.pass_directions.forward.total}"
            if dist.pass_directions.forward.total
            else directions.forward
        ),
    )
    d2.metric(
        "Sideways",
        (
            f"{dist.pass_directions.sideways.success}/{dist.pass_directions.sideways.total}"
            if dist.pass_directions.sideways.total
            else directions.sideways
        ),
    )
    d3.metric(
        "Backward",
        (
            f"{dist.pass_directions.backward.success}/{dist.pass_directions.backward.total}"
            if dist.pass_directions.backward.total
            else directions.backward
        ),
    )
    st.markdown("**Chance creation**")
    st.dataframe(
        _split_rows(
            ("Crosses", dist.crosses),
            ("Progressive passes", dist.progressive_passes),
            ("Cutbacks", dist.cutbacks),
        ),
        hide_index=True,
        width="stretch",
    )


def render_possession(profile: PlayerMatchProfile) -> None:
    """Possession time, share, recoveries, and balls lost."""

    st.subheader("Possession")
    st.caption("On-ball time plus recoveries and turnovers by third.")
    possession = profile.possession
    p1, p2 = st.columns(2)
    p1.metric("Possession time", f"{possession.time_minutes:.1f} min")
    p2.metric("Possession %", f"{possession.percentage:.1f}%")
    recoveries = profile.defensive.ball_recoveries
    lost = profile.defensive.ball_lost
    st.markdown("**Recoveries / ball lost**")
    st.dataframe(
        [
            {
                "Third": "Defensive",
                "Recoveries": recoveries.defensive_third,
                "Ball lost": lost.defensive_third,
            },
            {
                "Third": "Middle",
                "Recoveries": recoveries.middle_third,
                "Ball lost": lost.middle_third,
            },
            {
                "Third": "Final",
                "Recoveries": recoveries.final_third,
                "Ball lost": lost.final_third,
            },
        ],
        hide_index=True,
        width="stretch",
    )


def render_tactical_pitch(actions: tuple[PitchAction, ...]) -> None:
    """Interactive 2D pitch: selected player's shots and passes."""

    st.subheader("Tactical pitch")
    st.caption(
        "Shot and pass locations on the FIFA 0–100 tagging grid "
        "(touchlines, halfway line, 18-yard boxes). "
        "Tags without valid coordinates are omitted."
    )
    fig, ax = draw_football_pitch()
    plotted, skipped = scatter_match_actions(ax, actions)
    st.pyplot(fig, width="stretch")
    plt.close(fig)
    if plotted == 0:
        st.info("No plottable shot or pass locations for this player.")
    elif skipped:
        st.caption(
            f"Plotted {plotted} actions. Skipped {skipped} tags with missing "
            "or out-of-range coordinates."
        )
    else:
        st.caption(f"Plotted {plotted} shot and pass locations.")


def render_dashboard(load: ProfileLoad) -> None:
    """Compose the three-pillar layout and pitch map for one loaded profile."""

    profile = load.profile
    header_l, header_r = st.columns([3, 1])
    with header_l:
        jersey = f"#{profile.jersey_number} " if profile.jersey_number else ""
        name = profile.player_name or profile.position or "Player"
        st.title("EnjoyStats")
        st.markdown("### Player match dashboard")
        st.write(
            f"{jersey}{name}  ·  {profile.position or 'Player'}  ·  "
            f"match `{profile.match_id}`  ·  player `{profile.player_id}`"
        )
    with header_r:
        if load.source == "live":
            st.success("Live FastAPI")
        else:
            st.warning("Dummy fallback")
        st.caption(load.message)

    top_l, top_r = st.columns(2)
    with top_l:
        render_offensive(profile)
    with top_r:
        render_defensive(profile)
    bottom_l, bottom_r = st.columns(2)
    with bottom_l:
        render_distribution(profile, load.directions)
    with bottom_r:
        render_possession(profile)
    render_tactical_pitch(load.actions)


def render_sidebar() -> tuple[str, UUID, UUID]:
    """Match / player selectors that drive the GET request."""

    st.sidebar.header("Match selection")
    st.sidebar.caption("Choosing a match or player loads `/api/v1/matches/{id}/players/{id}`.")
    base_url = st.sidebar.text_input("FastAPI base URL", value=DEFAULT_BASE_URL)
    matches = _match_options()
    match_label = st.sidebar.selectbox("Match UUID", options=list(matches.keys()))
    match_id = matches[match_label]
    players = _player_options(match_id)
    player_label = st.sidebar.selectbox("Player ID", options=list(players.keys()))
    player_id = players[player_label]
    st.sidebar.divider()
    st.sidebar.caption("If FastAPI is down, dummy values for this selection still render.")
    return base_url.strip() or DEFAULT_BASE_URL, match_id, player_id


def main(*, fetch: FetchFn = _run_fetch) -> None:
    """Streamlit entry point. ``fetch`` is injectable for tests."""

    st.set_page_config(
        page_title="EnjoyStats · Player dashboard",
        page_icon="⚽",
        layout="wide",
    )
    _inject_styles()
    base_url, match_id, player_id = render_sidebar()
    load = fetch(base_url, match_id, player_id)
    render_dashboard(load)


if __name__ == "__main__":
    main()
