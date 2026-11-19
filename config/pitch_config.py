"""FIFA-standard pitch geometry and normalized-grid spatial classification.

Coordinate conventions
----------------------
The tagging pipeline stores locations on a **normalized 0–100 grid**:

* ``x = 0`` is the tagged team's own goal line; ``x = 100`` is the opponent's
  goal line once the point has been oriented attacking left-to-right.
* ``y = 0`` is the left touchline in that same attacking frame; ``y = 100`` is
  the right touchline.
* Values are inclusive of the boundary lines (``0`` and ``100``).

When ``attacking_left_to_right`` is ``False``, both axes are mirrored so that
a broadcast/fixed-camera feed (x = 0 on the left of screen) is converted into
the attacking frame before thirds and penalty areas are evaluated.

Physical constants follow IFAB Law 1 for a standard international pitch of
105 m × 68 m. Penalty-area depth is 16.5 m; penalty-area width is 40.32 m
(16.5 m either side of a 7.32 m goal). Tactical thirds split the length into
three equal 35 m bands, which map to ``[0, 100/3)``, ``[100/3, 200/3)``, and
``[200/3, 100]`` on the normalized grid.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

FIFA_PITCH_LENGTH_M: Final[float] = 105.0
FIFA_PITCH_WIDTH_M: Final[float] = 68.0

GOAL_WIDTH_M: Final[float] = 7.32
PENALTY_AREA_DEPTH_M: Final[float] = 16.5
PENALTY_AREA_LATERAL_MARGIN_M: Final[float] = 16.5
PENALTY_AREA_WIDTH_M: Final[float] = GOAL_WIDTH_M + (2.0 * PENALTY_AREA_LATERAL_MARGIN_M)  # 40.32 m

GOAL_AREA_DEPTH_M: Final[float] = 5.5
GOAL_AREA_WIDTH_M: Final[float] = GOAL_WIDTH_M + (2.0 * GOAL_AREA_DEPTH_M)  # 18.32 m
PENALTY_SPOT_DISTANCE_M: Final[float] = 11.0
CENTRE_CIRCLE_RADIUS_M: Final[float] = 9.15
CORNER_ARC_RADIUS_M: Final[float] = 1.0
PENALTY_ARC_RADIUS_M: Final[float] = 9.15

NORMALIZED_MIN: Final[float] = 0.0
NORMALIZED_MAX: Final[float] = 100.0
THIRD_BOUNDARY_COUNT: Final[int] = 3


class PitchThird(StrEnum):
    """Lengthwise tactical thirds, from the tagged team's attacking direction."""

    DEFENSIVE = "defensive"
    MIDDLE = "middle"
    FINAL = "final"


class PenaltyBox(StrEnum):
    """Which penalty area, if any, contains a location."""

    NONE = "none"
    DEFENSIVE = "defensive"
    ATTACKING = "attacking"


@dataclass(frozen=True, slots=True)
class PitchDimensions:
    """Physical pitch measurements used to project the 0–100 tagging grid.

    Attributes:
        length_m: Touchline length in metres (IFAB: 90–120, FIFA match: 105).
        width_m: Goal-line width in metres (IFAB: 45–90, FIFA match: 68).
        penalty_area_depth_m: Distance from each goal line to the 18-yard line.
        penalty_area_width_m: Distance between the penalty-area side lines.
        goal_area_depth_m: Distance from each goal line to the 6-yard line.
        goal_area_width_m: Distance between the goal-area side lines.
        goal_width_m: Distance between the insides of the posts.
        penalty_spot_distance_m: Distance from the goal line to the penalty mark.
    """

    length_m: float = FIFA_PITCH_LENGTH_M
    width_m: float = FIFA_PITCH_WIDTH_M
    penalty_area_depth_m: float = PENALTY_AREA_DEPTH_M
    penalty_area_width_m: float = PENALTY_AREA_WIDTH_M
    goal_area_depth_m: float = GOAL_AREA_DEPTH_M
    goal_area_width_m: float = GOAL_AREA_WIDTH_M
    goal_width_m: float = GOAL_WIDTH_M
    penalty_spot_distance_m: float = PENALTY_SPOT_DISTANCE_M

    def __post_init__(self) -> None:
        if self.length_m <= 0 or self.width_m <= 0:
            raise ValueError("Pitch length and width must be positive.")
        if self.penalty_area_depth_m <= 0 or self.penalty_area_width_m <= 0:
            raise ValueError("Penalty-area dimensions must be positive.")
        if self.penalty_area_depth_m * 2 >= self.length_m:
            raise ValueError("Penalty areas would overlap on this pitch length.")
        if self.penalty_area_width_m > self.width_m:
            raise ValueError("Penalty-area width cannot exceed pitch width.")

    @property
    def penalty_area_depth_norm(self) -> float:
        """Penalty-area depth as a 0–100 fraction of pitch length."""

        return (self.penalty_area_depth_m / self.length_m) * NORMALIZED_MAX

    @property
    def penalty_area_y_min_norm(self) -> float:
        """Lower y bound of both penalty areas on the 0–100 width axis."""

        lateral_m = (self.width_m - self.penalty_area_width_m) / 2.0
        return (lateral_m / self.width_m) * NORMALIZED_MAX

    @property
    def penalty_area_y_max_norm(self) -> float:
        """Upper y bound of both penalty areas on the 0–100 width axis."""

        return NORMALIZED_MAX - self.penalty_area_y_min_norm

    @property
    def defensive_penalty_x_max_norm(self) -> float:
        """Maximum normalized x still inside the defensive penalty area."""

        return self.penalty_area_depth_norm

    @property
    def attacking_penalty_x_min_norm(self) -> float:
        """Minimum normalized x still inside the attacking penalty area."""

        return NORMALIZED_MAX - self.penalty_area_depth_norm

    @property
    def third_length_norm(self) -> float:
        """Normalized length of one tactical third."""

        return NORMALIZED_MAX / THIRD_BOUNDARY_COUNT

    @property
    def defensive_third_x_max_norm(self) -> float:
        """Exclusive upper x bound of the defensive third."""

        return self.third_length_norm

    @property
    def final_third_x_min_norm(self) -> float:
        """Inclusive lower x bound of the final third."""

        return self.third_length_norm * 2.0

    def third_boundaries_norm(self) -> tuple[float, float, float, float]:
        """Return ``(0, defensive_max, final_min, 100)`` on the length axis."""

        return (
            NORMALIZED_MIN,
            self.defensive_third_x_max_norm,
            self.final_third_x_min_norm,
            NORMALIZED_MAX,
        )


FIFA_PITCH: Final[PitchDimensions] = PitchDimensions()


@dataclass(frozen=True, slots=True)
class PenaltyAreaBounds:
    """Axis-aligned penalty-area rectangle on the oriented 0–100 grid.

    Attributes:
        box: Which penalty area this rectangle describes.
        x_min: Inclusive lower bound on the length axis.
        x_max: Inclusive upper bound on the length axis.
        y_min: Inclusive lower bound on the width axis.
        y_max: Inclusive upper bound on the width axis.
    """

    box: PenaltyBox
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        """Return whether the oriented point lies inside this rectangle."""

        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


@dataclass(frozen=True, slots=True)
class PitchLocation:
    """A tagged point after projection from the 0–100 grid into tactical space.

    Attributes:
        x: Normalized length coordinate in ``[0, 100]``, attacking L→R.
        y: Normalized width coordinate in ``[0, 100]``, left→right.
        x_m: Physical length coordinate in metres from the own goal line.
        y_m: Physical width coordinate in metres from the left touchline.
        third: Tactical third containing the point.
        penalty_box: Penalty area containing the point, if any.
        in_penalty_area: Convenience flag equivalent to ``penalty_box != NONE``.
    """

    x: float
    y: float
    x_m: float
    y_m: float
    third: PitchThird
    penalty_box: PenaltyBox
    in_penalty_area: bool


def _ensure_normalized(value: float, axis: Literal["x", "y"]) -> float:
    """Return ``value`` if it sits on the closed 0–100 interval.

    Args:
        value: Candidate coordinate.
        axis: Axis name used in the error message.

    Returns:
        The original value when it is in range.

    Raises:
        ValueError: If ``value`` is outside ``[0, 100]``.
    """

    if value < NORMALIZED_MIN or value > NORMALIZED_MAX:
        raise ValueError(
            f"Normalized {axis} must be in [{NORMALIZED_MIN}, {NORMALIZED_MAX}], got {value}."
        )
    return value


def _orient_axis(value: float, *, attacking_left_to_right: bool) -> float:
    """Mirror a 0–100 axis when the team is attacking right-to-left.

    Args:
        value: Normalized coordinate as stored on the raw event.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        The coordinate expressed in the attacking-left-to-right frame.
    """

    if attacking_left_to_right:
        return value
    return NORMALIZED_MAX - value


def _orient_point(
    x: float,
    y: float,
    *,
    attacking_left_to_right: bool,
) -> tuple[float, float]:
    """Validate and orient a raw 0–100 point into the attacking frame.

    Args:
        x: Raw normalized length coordinate.
        y: Raw normalized width coordinate.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        ``(oriented_x, oriented_y)`` with own-goal at x=0 and left touchline at y=0.
    """

    return (
        _orient_axis(_ensure_normalized(x, "x"), attacking_left_to_right=attacking_left_to_right),
        _orient_axis(_ensure_normalized(y, "y"), attacking_left_to_right=attacking_left_to_right),
    )


def penalty_area_bounds(
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    box: PenaltyBox,
) -> PenaltyAreaBounds:
    """Return the normalized rectangle for a penalty area.

    Args:
        pitch: Physical pitch whose penalty-area geometry is used.
        box: ``PenaltyBox.DEFENSIVE`` or ``PenaltyBox.ATTACKING``.

    Returns:
        Inclusive 0–100 bounds for the requested box.

    Raises:
        ValueError: If ``box`` is ``PenaltyBox.NONE``.
    """

    if box is PenaltyBox.NONE:
        raise ValueError("penalty_area_bounds requires DEFENSIVE or ATTACKING.")
    y_min = pitch.penalty_area_y_min_norm
    y_max = pitch.penalty_area_y_max_norm
    if box is PenaltyBox.DEFENSIVE:
        return PenaltyAreaBounds(
            box=PenaltyBox.DEFENSIVE,
            x_min=NORMALIZED_MIN,
            x_max=pitch.defensive_penalty_x_max_norm,
            y_min=y_min,
            y_max=y_max,
        )
    return PenaltyAreaBounds(
        box=PenaltyBox.ATTACKING,
        x_min=pitch.attacking_penalty_x_min_norm,
        x_max=NORMALIZED_MAX,
        y_min=y_min,
        y_max=y_max,
    )


def normalized_to_meters(
    x: float,
    y: float,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
) -> tuple[float, float]:
    """Convert a normalized 0–100 point into metre coordinates.

    Args:
        x: Normalized length coordinate.
        y: Normalized width coordinate.
        pitch: Physical pitch used for the projection.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        ``(x_m, y_m)`` measured from the own-goal / left-touchline origin in
        the attacking-left-to-right frame.
    """

    oriented_x, oriented_y = _orient_point(x, y, attacking_left_to_right=attacking_left_to_right)
    x_m = (oriented_x / NORMALIZED_MAX) * pitch.length_m
    y_m = (oriented_y / NORMALIZED_MAX) * pitch.width_m
    return x_m, y_m


def meters_to_normalized(
    x_m: float,
    y_m: float,
    pitch: PitchDimensions = FIFA_PITCH,
) -> tuple[float, float]:
    """Convert metre coordinates into the 0–100 tagging grid.

    Args:
        x_m: Metres from the own goal line toward the opponent's goal.
        y_m: Metres from the left touchline toward the right touchline.
        pitch: Physical pitch used for the projection.

    Returns:
        ``(x, y)`` on the closed 0–100 interval.

    Raises:
        ValueError: If the metre point lies outside the pitch rectangle.
    """

    if x_m < 0.0 or x_m > pitch.length_m:
        raise ValueError(f"x_m={x_m} is outside pitch length {pitch.length_m} m.")
    if y_m < 0.0 or y_m > pitch.width_m:
        raise ValueError(f"y_m={y_m} is outside pitch width {pitch.width_m} m.")
    x = (x_m / pitch.length_m) * NORMALIZED_MAX
    y = (y_m / pitch.width_m) * NORMALIZED_MAX
    return x, y


def map_to_pitch_third(
    x: float,
    y: float | None = None,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
) -> PitchThird:
    """Map a normalized 0–100 location onto a tactical third.

    The defensive third is ``[0, 100/3)``, the middle third is
    ``[100/3, 200/3)``, and the final third is ``[200/3, 100]``. The far
    goal-line point ``x = 100`` is therefore classified as the final third.
    ``y`` is accepted so callers can pass a full point; it is range-checked
    and oriented when provided but does not affect the third.

    Args:
        x: Normalized length coordinate.
        y: Optional normalized width coordinate, validated when supplied.
        pitch: Physical pitch whose third boundaries are used.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        The tactical third containing the oriented length coordinate.
    """

    if y is None:
        oriented_x = _orient_axis(
            _ensure_normalized(x, "x"),
            attacking_left_to_right=attacking_left_to_right,
        )
    else:
        oriented_x, _oriented_y = _orient_point(
            x, y, attacking_left_to_right=attacking_left_to_right
        )
    if oriented_x < pitch.defensive_third_x_max_norm:
        return PitchThird.DEFENSIVE
    if oriented_x < pitch.final_third_x_min_norm:
        return PitchThird.MIDDLE
    return PitchThird.FINAL


def is_inside_penalty_area(
    x: float,
    y: float,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
    box: PenaltyBox | None = None,
) -> bool:
    """Return whether a normalized point lies inside a penalty area.

    Boundary points on the 18-yard lines are counted as inside, matching IFAB
    "whole of the ball over the line" treatment inverted for tagging: a point
    on the line is in the area.

    Args:
        x: Normalized length coordinate.
        y: Normalized width coordinate.
        pitch: Physical pitch whose penalty-area rectangle is used.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.
        box: When set, test only that penalty area; otherwise test either box.

    Returns:
        ``True`` if the oriented point is inside the requested area(s).
    """

    oriented_x, oriented_y = _orient_point(x, y, attacking_left_to_right=attacking_left_to_right)
    if box is PenaltyBox.DEFENSIVE:
        return penalty_area_bounds(pitch, box=PenaltyBox.DEFENSIVE).contains(oriented_x, oriented_y)
    if box is PenaltyBox.ATTACKING:
        return penalty_area_bounds(pitch, box=PenaltyBox.ATTACKING).contains(oriented_x, oriented_y)
    return penalty_area_bounds(pitch, box=PenaltyBox.DEFENSIVE).contains(
        oriented_x, oriented_y
    ) or penalty_area_bounds(pitch, box=PenaltyBox.ATTACKING).contains(oriented_x, oriented_y)


def penalty_box_for_point(
    x: float,
    y: float,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
) -> PenaltyBox:
    """Return which penalty area contains a normalized point.

    Args:
        x: Normalized length coordinate.
        y: Normalized width coordinate.
        pitch: Physical pitch whose penalty-area rectangles are used.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        ``PenaltyBox.DEFENSIVE``, ``PenaltyBox.ATTACKING``, or ``PenaltyBox.NONE``.
    """

    if is_inside_penalty_area(
        x,
        y,
        pitch,
        attacking_left_to_right=attacking_left_to_right,
        box=PenaltyBox.DEFENSIVE,
    ):
        return PenaltyBox.DEFENSIVE
    if is_inside_penalty_area(
        x,
        y,
        pitch,
        attacking_left_to_right=attacking_left_to_right,
        box=PenaltyBox.ATTACKING,
    ):
        return PenaltyBox.ATTACKING
    return PenaltyBox.NONE


def classify_normalized_point(
    x: float,
    y: float,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
) -> PitchLocation:
    """Project a 0–100 grid point into thirds, penalty areas, and metres.

    Args:
        x: Normalized length coordinate.
        y: Normalized width coordinate.
        pitch: Physical pitch used for the projection.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        A frozen :class:`PitchLocation` describing the oriented point.
    """

    oriented_x, oriented_y = _orient_point(x, y, attacking_left_to_right=attacking_left_to_right)
    x_m, y_m = normalized_to_meters(
        oriented_x,
        oriented_y,
        pitch,
        attacking_left_to_right=True,
    )
    box = penalty_box_for_point(
        oriented_x,
        oriented_y,
        pitch,
        attacking_left_to_right=True,
    )
    return PitchLocation(
        x=oriented_x,
        y=oriented_y,
        x_m=x_m,
        y_m=y_m,
        third=map_to_pitch_third(oriented_x, oriented_y, pitch, attacking_left_to_right=True),
        penalty_box=box,
        in_penalty_area=box is not PenaltyBox.NONE,
    )


def map_player_coordinates(
    x: float,
    y: float,
    pitch: PitchDimensions = FIFA_PITCH,
    *,
    attacking_left_to_right: bool = True,
) -> PitchLocation:
    """Map a player's 0–100 position onto thirds and penalty-area boundaries.

    This is the primary entry point for live tagging: it orients the raw grid
    point, projects it onto the FIFA 105 m × 68 m pitch, and returns the
    tactical third plus which penalty area (if any) contains the player.

    Args:
        x: Normalized length coordinate on the 0–100 grid.
        y: Normalized width coordinate on the 0–100 grid.
        pitch: Physical pitch used for the projection. Defaults to FIFA standard.
        attacking_left_to_right: Whether the tagged team attacks toward x=100.

    Returns:
        A :class:`PitchLocation` with metre coordinates, :class:`PitchThird`,
        and :class:`PenaltyBox` classification.
    """

    return classify_normalized_point(
        x,
        y,
        pitch,
        attacking_left_to_right=attacking_left_to_right,
    )
