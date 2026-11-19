"""Match-event schemas for real-time and post-match football tagging."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from config.pitch_config import (
    FIFA_PITCH,
    PenaltyBox,
    PitchLocation,
    PitchThird,
    classify_normalized_point,
)
from data_models.player_stats import StrictModel


class EventType(StrEnum):
    """Canonical event types consumed by the tagging and aggregation pipeline."""

    PASS = "pass"
    CROSS = "cross"
    CUTBACK = "cutback"
    SHOT = "shot"
    GOAL = "goal"
    ASSIST = "assist"
    AERIAL_DUEL = "aerial_duel"
    GROUND_DUEL = "ground_duel"
    BLOCK_SHOT = "block_shot"
    BLOCK_CROSS = "block_cross"
    BLOCK_PASS = "block_pass"
    FOUL_COMMITTED = "foul_committed"
    FOUL_WON = "foul_won"
    INTERCEPTION = "interception"
    BALL_RECOVERY = "ball_recovery"
    BALL_LOST = "ball_lost"
    OFFSIDE = "offside"
    FREE_KICK = "free_kick"
    CORNER = "corner"
    THROW_IN = "throw_in"
    YELLOW_CARD = "yellow_card"
    RED_CARD = "red_card"
    GOAL_CONCEDED = "goal_conceded"


class ShotOutcome(StrEnum):
    """Mutually exclusive shot results used by :class:`OffensiveStats`."""

    ON_TARGET = "on_target"
    BLOCKED = "blocked"
    MISSED = "missed"


class PassLengthBand(StrEnum):
    """Pass length bands measured in metres on the FIFA pitch."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


SHORT_PASS_MAX_M = 15.0
MEDIUM_PASS_MAX_M = 30.0


def pass_length_band(distance_m: float) -> PassLengthBand:
    """Classify a pass distance into short / medium / long.

    Args:
        distance_m: Pass travel distance in metres.

    Returns:
        The length band for ``distance_m``.
    """

    if distance_m < SHORT_PASS_MAX_M:
        return PassLengthBand.SHORT
    if distance_m <= MEDIUM_PASS_MAX_M:
        return PassLengthBand.MEDIUM
    return PassLengthBand.LONG


class MatchEvent(StrictModel):
    """A single tagged on-ball action, live or post-match.

    Coordinates are stored on the normalized 0–100 grid. ``end_x`` / ``end_y``
    are required for distribution events so progressive and penalty-area
    destinations can be derived.

    Attributes:
        event_id: Stable identifier for the tagged action.
        match_id: Parent match.
        team_id: Team in possession / performing the action.
        player_id: Primary actor; omitted for some stoppages.
        period: Match period (1–2 regulation, 3–4 extra time, 5 penalties).
        minute: Clock minute within the period, including stoppage.
        second: Clock second within the minute.
        event_type: Canonical action type.
        x: Normalized start location on the length axis.
        y: Normalized start location on the width axis.
        end_x: Normalized end location on the length axis, if applicable.
        end_y: Normalized end location on the width axis, if applicable.
        successful: Outcome flag for attempts (passes, duels, shots on target).
        is_goal: Whether a shot resulted in a goal.
        is_assist: Whether a pass was credited as an assist.
        is_progressive: Whether a pass is tagged as progressive.
        is_penalty: Whether a shot was taken from the penalty spot.
        shot_outcome: Shot result, required when ``event_type`` is shot/goal.
        attacking_left_to_right: Team attacking direction for this period.
        video_timestamp_ms: Seek offset in the match video, in milliseconds.
        clip_url: Highlight clip URL used by the AutoData Advanced playlist.
        recorded_at: UTC timestamp when the tag was received.
    """

    event_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    team_id: UUID
    player_id: UUID | None = None
    period: int = Field(default=1, ge=1, le=5)
    minute: int = Field(ge=0, le=150)
    second: int = Field(default=0, ge=0, le=59)
    event_type: EventType
    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    end_x: float | None = Field(default=None, ge=0.0, le=100.0)
    end_y: float | None = Field(default=None, ge=0.0, le=100.0)
    successful: bool = True
    is_goal: bool = False
    is_assist: bool = False
    is_progressive: bool = False
    is_penalty: bool = False
    shot_outcome: ShotOutcome | None = None
    attacking_left_to_right: bool = True
    video_timestamp_ms: int = Field(
        default=0,
        ge=0,
        description="Seek offset in the match video, in milliseconds.",
    )
    clip_url: str = Field(
        default="",
        max_length=2048,
        description="Highlight clip URL for clickable playlist anchors.",
    )
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("second")
    @classmethod
    def second_in_minute(cls, value: int) -> int:
        """Keep seconds on a clock minute."""

        return value

    @model_validator(mode="after")
    def distribution_and_shots_carry_required_payload(self) -> Self:
        """Require end coordinates for passes and a shot outcome for shots."""

        distribution_types = {
            EventType.PASS,
            EventType.CROSS,
            EventType.CUTBACK,
            EventType.ASSIST,
        }
        if self.event_type in distribution_types:
            if self.end_x is None or self.end_y is None:
                raise ValueError("Pass-like events require end_x and end_y.")
        if self.event_type in {EventType.SHOT, EventType.GOAL}:
            if self.shot_outcome is None:
                raise ValueError("Shot events require shot_outcome.")
            if self.event_type is EventType.GOAL and not self.is_goal:
                raise ValueError("GOAL events must set is_goal=True.")
            if self.is_goal and self.shot_outcome is not ShotOutcome.ON_TARGET:
                raise ValueError("Goals must have shot_outcome=on_target.")
        return self

    @property
    def pass_distance_m(self) -> float | None:
        """Euclidean pass distance in metres, or ``None`` when no end point."""

        if self.end_x is None or self.end_y is None:
            return None
        start = classify_normalized_point(
            self.x,
            self.y,
            FIFA_PITCH,
            attacking_left_to_right=self.attacking_left_to_right,
        )
        end = classify_normalized_point(
            self.end_x,
            self.end_y,
            FIFA_PITCH,
            attacking_left_to_right=self.attacking_left_to_right,
        )
        dx = end.x_m - start.x_m
        dy = end.y_m - start.y_m
        return (dx * dx + dy * dy) ** 0.5


class TaggedMatchEvent(MatchEvent):
    """A match event enriched with pitch-third and penalty-area classification."""

    start_location: PitchLocation
    end_location: PitchLocation | None = None
    start_third: PitchThird
    start_penalty_box: PenaltyBox
    end_in_attacking_penalty_area: bool = False
    pass_band: PassLengthBand | None = None

    @classmethod
    def from_event(cls, event: MatchEvent) -> TaggedMatchEvent:
        """Classify an incoming event against the FIFA pitch.

        Args:
            event: Raw tagged event on the 0–100 grid.

        Returns:
            The same event with start/end spatial metadata attached.
        """

        start = classify_normalized_point(
            event.x,
            event.y,
            FIFA_PITCH,
            attacking_left_to_right=event.attacking_left_to_right,
        )
        end: PitchLocation | None = None
        end_in_box = False
        band: PassLengthBand | None = None
        if event.end_x is not None and event.end_y is not None:
            end = classify_normalized_point(
                event.end_x,
                event.end_y,
                FIFA_PITCH,
                attacking_left_to_right=event.attacking_left_to_right,
            )
            end_in_box = end.penalty_box is PenaltyBox.ATTACKING
            if event.pass_distance_m is not None:
                band = pass_length_band(event.pass_distance_m)
        payload = event.model_dump()
        return cls(
            **payload,
            start_location=start,
            end_location=end,
            start_third=start.third,
            start_penalty_box=start.penalty_box,
            end_in_attacking_penalty_area=end_in_box,
            pass_band=band,
        )
