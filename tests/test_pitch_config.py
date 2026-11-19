"""Tests for FIFA pitch geometry and 0–100 grid classification."""

from __future__ import annotations

import pytest

from config.pitch_config import (
    FIFA_PITCH,
    FIFA_PITCH_LENGTH_M,
    FIFA_PITCH_WIDTH_M,
    PENALTY_AREA_DEPTH_M,
    PENALTY_AREA_WIDTH_M,
    PenaltyBox,
    PitchDimensions,
    PitchThird,
    is_inside_penalty_area,
    map_player_coordinates,
    map_to_pitch_third,
    meters_to_normalized,
    normalized_to_meters,
    penalty_area_bounds,
)


def test_fifa_pitch_is_105_by_68() -> None:
    assert FIFA_PITCH.length_m == FIFA_PITCH_LENGTH_M == 105.0
    assert FIFA_PITCH.width_m == FIFA_PITCH_WIDTH_M == 68.0
    assert PENALTY_AREA_DEPTH_M == 16.5
    assert PENALTY_AREA_WIDTH_M == pytest.approx(40.32)


@pytest.mark.parametrize(
    ("x", "expected"),
    [
        (0.0, PitchThird.DEFENSIVE),
        (33.3, PitchThird.DEFENSIVE),
        (100.0 / 3.0 - 1e-9, PitchThird.DEFENSIVE),
        (100.0 / 3.0, PitchThird.MIDDLE),
        (50.0, PitchThird.MIDDLE),
        (200.0 / 3.0 - 1e-9, PitchThird.MIDDLE),
        (200.0 / 3.0, PitchThird.FINAL),
        (90.0, PitchThird.FINAL),
        (100.0, PitchThird.FINAL),
    ],
)
def test_tactical_thirds_on_attacking_frame(x: float, expected: PitchThird) -> None:
    assert map_to_pitch_third(x, 50.0) is expected


def test_thirds_flip_when_attacking_right_to_left() -> None:
    assert map_to_pitch_third(5.0, 50.0, attacking_left_to_right=False) is PitchThird.FINAL
    assert map_to_pitch_third(95.0, 50.0, attacking_left_to_right=False) is PitchThird.DEFENSIVE
    assert map_to_pitch_third(50.0, 50.0, attacking_left_to_right=False) is PitchThird.MIDDLE


def test_penalty_area_centre_spots() -> None:
    defensive = map_player_coordinates(5.0, 50.0)
    attacking = map_player_coordinates(95.0, 50.0)
    midfield = map_player_coordinates(50.0, 50.0)

    assert defensive.third is PitchThird.DEFENSIVE
    assert defensive.penalty_box is PenaltyBox.DEFENSIVE
    assert defensive.in_penalty_area is True

    assert attacking.third is PitchThird.FINAL
    assert attacking.penalty_box is PenaltyBox.ATTACKING
    assert attacking.in_penalty_area is True

    assert midfield.penalty_box is PenaltyBox.NONE
    assert midfield.in_penalty_area is False


def test_eighteen_yard_line_is_inside_the_box() -> None:
    depth_norm = FIFA_PITCH.penalty_area_depth_norm
    on_line = map_player_coordinates(depth_norm, 50.0)
    just_outside = map_player_coordinates(depth_norm + 0.01, 50.0)
    assert on_line.penalty_box is PenaltyBox.DEFENSIVE
    assert just_outside.penalty_box is PenaltyBox.NONE


def test_penalty_area_lateral_boundary() -> None:
    y_min = FIFA_PITCH.penalty_area_y_min_norm
    inside = map_player_coordinates(10.0, y_min)
    outside = map_player_coordinates(10.0, y_min - 0.01)
    assert inside.penalty_box is PenaltyBox.DEFENSIVE
    assert outside.penalty_box is PenaltyBox.NONE


def test_wide_channel_is_not_inside_the_box() -> None:
    assert is_inside_penalty_area(92.0, 5.0) is False
    assert is_inside_penalty_area(92.0, 50.0) is True


def test_normalized_metre_roundtrip_centre_spot() -> None:
    x_m, y_m = normalized_to_meters(50.0, 50.0)
    assert x_m == pytest.approx(52.5)
    assert y_m == pytest.approx(34.0)
    x, y = meters_to_normalized(x_m, y_m)
    assert x == pytest.approx(50.0)
    assert y == pytest.approx(50.0)


def test_out_of_range_coordinates_are_rejected() -> None:
    with pytest.raises(ValueError, match="Normalized x"):
        map_player_coordinates(-0.1, 50.0)
    with pytest.raises(ValueError, match="Normalized y"):
        map_player_coordinates(50.0, 100.1)


def test_penalty_area_bounds_match_fifa_metres() -> None:
    attacking = penalty_area_bounds(box=PenaltyBox.ATTACKING)
    x_min_m = (attacking.x_min / 100.0) * FIFA_PITCH_LENGTH_M
    assert x_min_m == pytest.approx(FIFA_PITCH_LENGTH_M - PENALTY_AREA_DEPTH_M)
    width_m = ((attacking.y_max - attacking.y_min) / 100.0) * FIFA_PITCH_WIDTH_M
    assert width_m == pytest.approx(PENALTY_AREA_WIDTH_M)


def test_custom_pitch_rejects_overlapping_boxes() -> None:
    with pytest.raises(ValueError, match="overlap"):
        PitchDimensions(length_m=20.0, penalty_area_depth_m=16.5)
