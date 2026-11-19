"""Tests for the 2D tactical pitch plot and missing-coordinate handling."""

from __future__ import annotations

import math
from uuid import uuid4

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from app.dashboard import (
    draw_football_pitch,
    has_valid_pitch_point,
    scatter_match_actions,
)
from app.dummy_data import (
    CONTROLLER_ID,
    PLAYMAKER_ID,
    SHOWCASE_MATCH_ID,
    SIM_MATCH_ID,
    STRIKER_ID,
    PitchAction,
    fallback_actions,
    match_actions,
)
from config.pitch_config import FIFA_PITCH, NORMALIZED_MAX, NORMALIZED_MIN


def test_has_valid_pitch_point_rejects_missing_and_out_of_range() -> None:
    assert has_valid_pitch_point(50.0, 50.0) is True
    assert has_valid_pitch_point(0.0, 100.0) is True
    assert has_valid_pitch_point(None, 50.0) is False
    assert has_valid_pitch_point(40.0, None) is False
    assert has_valid_pitch_point(math.nan, 50.0) is False
    assert has_valid_pitch_point(50.0, math.inf) is False
    assert has_valid_pitch_point(-0.1, 50.0) is False
    assert has_valid_pitch_point(50.0, 100.1) is False


def test_draw_football_pitch_uses_normalized_0_100_grid() -> None:
    fig, ax = draw_football_pitch()
    try:
        assert ax.get_xlim() == (NORMALIZED_MIN, NORMALIZED_MAX)
        assert ax.get_ylim() == (NORMALIZED_MIN, NORMALIZED_MAX)
        rectangles = [patch for patch in ax.patches if isinstance(patch, Rectangle)]
        touchlines = [
            patch
            for patch in rectangles
            if patch.get_width() == 100.0 and patch.get_height() == 100.0
        ]
        assert touchlines, "Expected a 0–100 touchline rectangle."
        box_depth = FIFA_PITCH.penalty_area_depth_norm
        penalty_boxes = [patch for patch in rectangles if abs(patch.get_width() - box_depth) < 1e-9]
        assert len(penalty_boxes) == 2
        xs = sorted(patch.get_x() for patch in penalty_boxes)
        assert xs[0] == NORMALIZED_MIN
        assert abs(xs[1] - FIFA_PITCH.attacking_penalty_x_min_norm) < 1e-9
        midfield = [line for line in ax.lines if list(line.get_xdata()) == [50.0, 50.0]]
        assert midfield, "Expected a vertical midfield line at x=50."
    finally:
        plt.close(fig)


def test_scatter_skips_missing_coordinates_and_marks_goals() -> None:
    fig, ax = draw_football_pitch()
    try:
        actions = (
            PitchAction(
                event_type="shot",
                x=None,
                y=48.0,
                is_goal=True,
                shot_outcome="on_target",
            ),
            PitchAction(event_type="pass", x=40.0, y=None, end_x=55.0, end_y=50.0),
            PitchAction(
                event_type="shot",
                x=88.0,
                y=50.0,
                is_goal=True,
                shot_outcome="on_target",
            ),
            PitchAction(event_type="shot", x=82.0, y=35.0, shot_outcome="missed"),
            PitchAction(event_type="pass", x=42.0, y=48.0, end_x=50.0, end_y=50.0),
        )
        plotted, skipped = scatter_match_actions(ax, actions)
        assert plotted == 3
        assert skipped == 2
        labels = {text.get_text() for text in ax.get_legend().get_texts()}
        assert "GOAL" in labels
        assert "Missed shot" in labels
        assert "Completed pass" in labels
    finally:
        plt.close(fig)


def test_dummy_actions_cover_demo_players_and_missing_coords() -> None:
    playmaker = fallback_actions(SIM_MATCH_ID, PLAYMAKER_ID)
    striker = fallback_actions(SIM_MATCH_ID, STRIKER_ID)
    controller = fallback_actions(SHOWCASE_MATCH_ID, CONTROLLER_ID)
    generic = fallback_actions(uuid4(), uuid4())

    assert len(playmaker) == 3
    assert all(action.event_type == "pass" for action in playmaker)
    assert striker[0].is_goal is True
    assert striker[0].x == 88.0
    assert any(action.x is None for action in controller)
    assert any(action.x is None for action in generic)
    assert match_actions(uuid4(), uuid4(), include_generic=False) == ()
