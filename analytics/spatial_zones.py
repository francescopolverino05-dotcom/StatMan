"""Advanced pitch zonal subdivisions for AutoData Advanced.

Maps raw 0–100 coordinates onto:

* a 6×3 percentage-of-play grid
* pass-distribution quadrants
* final-third entry channels
* ball-lost / ball-recovered locations

Pass success rates are accumulated natively inside each sector with numpy.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Final
from uuid import UUID

import numpy as np
from pydantic import Field

from config.pitch_config import FIFA_PITCH, NORMALIZED_MAX, NORMALIZED_MIN, PitchThird
from data_models.events import EventType, MatchEvent
from data_models.player_stats import StrictModel
from data_models.video_sync import PASS_EVENT_TYPES

GRID_LENGTH_BINS: Final[int] = 6
GRID_WIDTH_BINS: Final[int] = 3
SECTOR_COUNT: Final[int] = GRID_LENGTH_BINS * GRID_WIDTH_BINS
FINAL_THIRD_X_MIN: Final[float] = FIFA_PITCH.final_third_x_min_norm


class PassQuadrant(StrEnum):
    """Four-way split of the attacking-left-to-right pitch."""

    DEFENSIVE_LEFT = "defensive_left"
    DEFENSIVE_RIGHT = "defensive_right"
    ATTACKING_LEFT = "attacking_left"
    ATTACKING_RIGHT = "attacking_right"


class PitchChannel(StrEnum):
    """Width channel on the attacking frame (y axis)."""

    LEFT = "left"
    CENTRE = "centre"
    RIGHT = "right"


class FinalThirdEntryZone(StrEnum):
    """Where a pass crosses the final-third line."""

    LEFT_CHANNEL = "left_channel"
    HALF_SPACE_LEFT = "half_space_left"
    CENTRE = "centre"
    HALF_SPACE_RIGHT = "half_space_right"
    RIGHT_CHANNEL = "right_channel"
    NONE = "none"


class PlayZone(StrictModel):
    """A coordinate mapped onto AutoData Advanced sectors."""

    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    x_pct: float = Field(ge=0.0, le=100.0)
    y_pct: float = Field(ge=0.0, le=100.0)
    length_bin: int = Field(ge=0, lt=GRID_LENGTH_BINS)
    width_bin: int = Field(ge=0, lt=GRID_WIDTH_BINS)
    sector_index: int = Field(ge=0, lt=SECTOR_COUNT)
    sector_key: str
    third: PitchThird
    channel: PitchChannel
    quadrant: PassQuadrant
    final_third_entry_zone: FinalThirdEntryZone = FinalThirdEntryZone.NONE


class SectorPassRate(StrictModel):
    """Pass attempts and success rate inside one pitch sector."""

    sector_key: str
    sector_index: int = Field(ge=0)
    length_bin: int = Field(ge=0)
    width_bin: int = Field(ge=0)
    attempts: int = Field(ge=0)
    completions: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    play_share: float = Field(ge=0.0, le=1.0)


class CoordinateTag(StrictModel):
    """A ball-lost or recovery location with its zone label."""

    event_id: UUID
    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    sector_key: str
    quadrant: PassQuadrant


class QuadrantPassRate(StrictModel):
    """Pass success inside a distribution quadrant."""

    quadrant: PassQuadrant
    attempts: int = Field(ge=0)
    completions: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)


class FinalThirdEntryCount(StrictModel):
    """Successful / attempted entries through one final-third channel."""

    zone: FinalThirdEntryZone
    attempts: int = Field(ge=0)
    completions: int = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)


class SpatialBreakdown(StrictModel):
    """Full AutoData Advanced spatial report for a match event set."""

    team_id: UUID | None = None
    player_id: UUID | None = None
    total_events: int = Field(ge=0)
    sectors: list[SectorPassRate]
    quadrants: list[QuadrantPassRate]
    final_third_entries: list[FinalThirdEntryCount]
    balls_lost: list[CoordinateTag]
    balls_recovered: list[CoordinateTag]


def _clip_norm(value: float) -> float:
    return min(NORMALIZED_MAX, max(NORMALIZED_MIN, float(value)))


def _bin_index(value: float, bins: int) -> int:
    if value >= NORMALIZED_MAX:
        return bins - 1
    return int((value / NORMALIZED_MAX) * bins)


def _channel(y: float) -> PitchChannel:
    width_bin = _bin_index(_clip_norm(y), GRID_WIDTH_BINS)
    if width_bin == 0:
        return PitchChannel.LEFT
    if width_bin == 1:
        return PitchChannel.CENTRE
    return PitchChannel.RIGHT


def _third(x: float) -> PitchThird:
    if x < FIFA_PITCH.defensive_third_x_max_norm:
        return PitchThird.DEFENSIVE
    if x < FIFA_PITCH.final_third_x_min_norm:
        return PitchThird.MIDDLE
    return PitchThird.FINAL


def _quadrant(x: float, y: float) -> PassQuadrant:
    attacking = x >= 50.0
    right = y >= 50.0
    if attacking and right:
        return PassQuadrant.ATTACKING_RIGHT
    if attacking:
        return PassQuadrant.ATTACKING_LEFT
    if right:
        return PassQuadrant.DEFENSIVE_RIGHT
    return PassQuadrant.DEFENSIVE_LEFT


def _entry_zone(y: float) -> FinalThirdEntryZone:
    clipped = _clip_norm(y)
    if clipped < 20.0:
        return FinalThirdEntryZone.LEFT_CHANNEL
    if clipped < 40.0:
        return FinalThirdEntryZone.HALF_SPACE_LEFT
    if clipped < 60.0:
        return FinalThirdEntryZone.CENTRE
    if clipped < 80.0:
        return FinalThirdEntryZone.HALF_SPACE_RIGHT
    return FinalThirdEntryZone.RIGHT_CHANNEL


def map_to_play_zone(x: float, y: float) -> PlayZone:
    """Map a raw 0–100 point onto percentage-of-play sectors.

    Args:
        x: Normalized length coordinate.
        y: Normalized width coordinate.

    Returns:
        A :class:`PlayZone` describing the sector, quadrant, channel, and third.
    """

    nx = _clip_norm(x)
    ny = _clip_norm(y)
    length_bin = _bin_index(nx, GRID_LENGTH_BINS)
    width_bin = _bin_index(ny, GRID_WIDTH_BINS)
    sector_index = width_bin * GRID_LENGTH_BINS + length_bin
    third = _third(nx)
    channel = _channel(ny)
    return PlayZone(
        x=nx,
        y=ny,
        x_pct=round(nx, 4),
        y_pct=round(ny, 4),
        length_bin=length_bin,
        width_bin=width_bin,
        sector_index=sector_index,
        sector_key=f"{third.value}_{channel.value}_{length_bin}",
        third=third,
        channel=channel,
        quadrant=_quadrant(nx, ny),
        final_third_entry_zone=(
            _entry_zone(ny) if nx >= FINAL_THIRD_X_MIN else FinalThirdEntryZone.NONE
        ),
    )


def _pass_events(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None,
    player_id: UUID | None,
) -> list[MatchEvent]:
    selected: list[MatchEvent] = []
    for event in events:
        if event.event_type not in PASS_EVENT_TYPES:
            continue
        if team_id is not None and event.team_id != team_id:
            continue
        if player_id is not None and event.player_id != player_id:
            continue
        selected.append(event)
    return selected


def sector_pass_rates(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
) -> list[SectorPassRate]:
    """Pass success rate inside each 6×3 pitch sector (numpy bincount)."""

    selected = _pass_events(events, team_id=team_id, player_id=player_id)
    attempts = np.zeros(SECTOR_COUNT, dtype=np.int64)
    completions = np.zeros(SECTOR_COUNT, dtype=np.int64)
    if selected:
        xs = np.fromiter((event.x for event in selected), dtype=np.float64, count=len(selected))
        ys = np.fromiter((event.y for event in selected), dtype=np.float64, count=len(selected))
        made = np.fromiter(
            (1 if event.successful else 0 for event in selected),
            dtype=np.int64,
            count=len(selected),
        )
        length_bins = np.clip(
            (xs / NORMALIZED_MAX * GRID_LENGTH_BINS).astype(np.int64), 0, GRID_LENGTH_BINS - 1
        )
        length_bins = np.where(xs >= NORMALIZED_MAX, GRID_LENGTH_BINS - 1, length_bins)
        width_bins = np.clip(
            (ys / NORMALIZED_MAX * GRID_WIDTH_BINS).astype(np.int64), 0, GRID_WIDTH_BINS - 1
        )
        width_bins = np.where(ys >= NORMALIZED_MAX, GRID_WIDTH_BINS - 1, width_bins)
        flat = width_bins * GRID_LENGTH_BINS + length_bins
        attempts = np.bincount(flat, minlength=SECTOR_COUNT)
        completions = np.bincount(flat, weights=made, minlength=SECTOR_COUNT).astype(np.int64)
    total_attempts = int(attempts.sum())
    rates: list[SectorPassRate] = []
    for index in range(SECTOR_COUNT):
        length_bin = index % GRID_LENGTH_BINS
        width_bin = index // GRID_LENGTH_BINS
        x_mid = (length_bin + 0.5) * (NORMALIZED_MAX / GRID_LENGTH_BINS)
        y_mid = (width_bin + 0.5) * (NORMALIZED_MAX / GRID_WIDTH_BINS)
        zone = map_to_play_zone(x_mid, y_mid)
        attempt_count = int(attempts[index])
        completion_count = int(completions[index])
        success = 0.0 if attempt_count == 0 else round(completion_count / attempt_count, 4)
        share = 0.0 if total_attempts == 0 else round(attempt_count / total_attempts, 4)
        rates.append(
            SectorPassRate(
                sector_key=zone.sector_key,
                sector_index=index,
                length_bin=length_bin,
                width_bin=width_bin,
                attempts=attempt_count,
                completions=completion_count,
                success_rate=success,
                play_share=share,
            )
        )
    return rates


def _is_final_third_entry(event: MatchEvent) -> bool:
    if event.end_x is None:
        return False
    return event.x < FINAL_THIRD_X_MIN <= event.end_x


def spatial_breakdown(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
) -> SpatialBreakdown:
    """Assemble sector rates, quadrants, entries, and turnover coordinates."""

    scoped = [
        event
        for event in events
        if (team_id is None or event.team_id == team_id)
        and (player_id is None or event.player_id == player_id)
    ]
    sectors = sector_pass_rates(scoped, team_id=team_id, player_id=player_id)
    quadrant_attempts = {item: 0 for item in PassQuadrant}
    quadrant_completions = {item: 0 for item in PassQuadrant}
    entry_attempts = {
        item: 0 for item in FinalThirdEntryZone if item is not FinalThirdEntryZone.NONE
    }
    entry_completions = {item: 0 for item in entry_attempts}
    lost: list[CoordinateTag] = []
    recovered: list[CoordinateTag] = []

    for event in scoped:
        zone = map_to_play_zone(event.x, event.y)
        if event.event_type in PASS_EVENT_TYPES:
            quadrant_attempts[zone.quadrant] += 1
            if event.successful:
                quadrant_completions[zone.quadrant] += 1
            if _is_final_third_entry(event):
                entry = _entry_zone(event.end_y if event.end_y is not None else event.y)
                entry_attempts[entry] += 1
                if event.successful:
                    entry_completions[entry] += 1
        if event.event_type is EventType.BALL_LOST:
            lost.append(
                CoordinateTag(
                    event_id=event.event_id,
                    x=zone.x,
                    y=zone.y,
                    sector_key=zone.sector_key,
                    quadrant=zone.quadrant,
                )
            )
        if event.event_type is EventType.BALL_RECOVERY:
            recovered.append(
                CoordinateTag(
                    event_id=event.event_id,
                    x=zone.x,
                    y=zone.y,
                    sector_key=zone.sector_key,
                    quadrant=zone.quadrant,
                )
            )

    quadrants = [
        QuadrantPassRate(
            quadrant=quadrant,
            attempts=quadrant_attempts[quadrant],
            completions=quadrant_completions[quadrant],
            success_rate=(
                0.0
                if quadrant_attempts[quadrant] == 0
                else round(quadrant_completions[quadrant] / quadrant_attempts[quadrant], 4)
            ),
        )
        for quadrant in PassQuadrant
    ]
    entries = [
        FinalThirdEntryCount(
            zone=zone,
            attempts=entry_attempts[zone],
            completions=entry_completions[zone],
            success_rate=(
                0.0
                if entry_attempts[zone] == 0
                else round(entry_completions[zone] / entry_attempts[zone], 4)
            ),
        )
        for zone in entry_attempts
    ]
    return SpatialBreakdown(
        team_id=team_id,
        player_id=player_id,
        total_events=len(scoped),
        sectors=sectors,
        quadrants=quadrants,
        final_third_entries=entries,
        balls_lost=lost,
        balls_recovered=recovered,
    )
