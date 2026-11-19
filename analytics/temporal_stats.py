"""Temporal aggregations for AutoData Advanced (numpy heatmaps and bins).

Computes:

* passes per 5-minute period
* ball-possession percentage in 15-minute segments
* pass-string length frequencies (consecutive successful team passes
  before a turnover)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from uuid import UUID

import numpy as np
from pydantic import Field

from data_models.events import EventType, MatchEvent
from data_models.player_stats import StrictModel
from data_models.video_sync import PASS_EVENT_TYPES, clock_minutes

PASS_BIN_MINUTES: Final[int] = 5
POSSESSION_BIN_MINUTES: Final[int] = 15
DEFAULT_MATCH_MINUTES: Final[int] = 90
TURNOVER_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {
        EventType.BALL_LOST,
        EventType.INTERCEPTION,
        EventType.FOUL_COMMITTED,
        EventType.GOAL_CONCEDED,
    }
)


class TemporalBin(StrictModel):
    """A single time-bucketed count."""

    start_minute: int = Field(ge=0)
    end_minute: int = Field(ge=0)
    label: str
    value: float = Field(ge=0.0)


class PassStringLengthCount(StrictModel):
    """How often a successful pass string of a given length occurred."""

    length: int = Field(ge=1)
    count: int = Field(ge=0)
    share: float = Field(ge=0.0, le=1.0)


class PassStringSummary(StrictModel):
    """Pass-sequence engine output: lengths and frequencies."""

    team_id: UUID | None = None
    total_strings: int = Field(ge=0)
    total_passes: int = Field(ge=0)
    longest_string: int = Field(ge=0)
    length_frequencies: list[PassStringLengthCount]


class TemporalBreakdown(StrictModel):
    """Passes-per-5-minutes plus possession-per-15-minutes."""

    team_id: UUID | None = None
    player_id: UUID | None = None
    passes_per_5_minutes: list[TemporalBin]
    possession_pct_per_15_minutes: list[TemporalBin]
    pass_strings: PassStringSummary


def _clock_array(events: Sequence[MatchEvent]) -> np.ndarray:
    """Vector of match-clock minutes for ``events``."""

    if not events:
        return np.empty(0, dtype=np.float64)
    return np.fromiter(
        (clock_minutes(event) for event in events), dtype=np.float64, count=len(events)
    )


def _bin_edges(bin_minutes: int, max_minute: int) -> np.ndarray:
    ceiling = max(max_minute, bin_minutes)
    last = int(np.ceil(ceiling / bin_minutes) * bin_minutes)
    return np.arange(0, last + bin_minutes, bin_minutes, dtype=np.float64)


def _histogram_bins(
    clocks: np.ndarray,
    *,
    bin_minutes: int,
    max_minute: int,
) -> list[TemporalBin]:
    edges = _bin_edges(bin_minutes, max_minute)
    counts, _ = np.histogram(clocks, bins=edges)
    bins: list[TemporalBin] = []
    for index, count in enumerate(counts.tolist()):
        start = int(edges[index])
        end = int(edges[index + 1])
        bins.append(
            TemporalBin(
                start_minute=start,
                end_minute=end,
                label=f"{start:02d}–{end:02d}",
                value=float(count),
            )
        )
    return bins


def _is_pass(event: MatchEvent) -> bool:
    return event.event_type in PASS_EVENT_TYPES


def _select_passes(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None,
    player_id: UUID | None,
) -> list[MatchEvent]:
    selected: list[MatchEvent] = []
    for event in events:
        if not _is_pass(event):
            continue
        if team_id is not None and event.team_id != team_id:
            continue
        if player_id is not None and event.player_id != player_id:
            continue
        selected.append(event)
    return selected


def passes_per_5_minute_period(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    max_minute: int = DEFAULT_MATCH_MINUTES,
) -> list[TemporalBin]:
    """Count passes in successive 5-minute windows using a numpy histogram.

    Args:
        events: Tagged match events in any order.
        team_id: Optional team filter.
        player_id: Optional player filter.
        max_minute: Right edge of the last bin (typically 90).

    Returns:
        One :class:`TemporalBin` per 5-minute window, including empty bins.
    """

    selected = _select_passes(events, team_id=team_id, player_id=player_id)
    clocks = _clock_array(selected)
    observed_max = int(np.ceil(float(clocks.max()))) if clocks.size else max_minute
    return _histogram_bins(
        clocks, bin_minutes=PASS_BIN_MINUTES, max_minute=max(max_minute, observed_max)
    )


def possession_pct_per_15_minute_segment(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID,
    max_minute: int = DEFAULT_MATCH_MINUTES,
) -> list[TemporalBin]:
    """Estimate ball-possession share in 15-minute segments.

    Possession time is the gap between consecutive on-ball events, attributed
    to the team that tagged the earlier event. Numpy bins the resulting
    durations.

    Args:
        events: Tagged match events for both teams when available.
        team_id: Team whose possession percentage is reported.
        max_minute: Right edge of the last segment.

    Returns:
        One :class:`TemporalBin` per 15-minute window. Values are percentages
        in ``[0, 100]``.
    """

    ordered = sorted(
        events, key=lambda item: (item.period, clock_minutes(item), str(item.event_id))
    )
    edges = _bin_edges(POSSESSION_BIN_MINUTES, max_minute)
    team_ms = np.zeros(len(edges) - 1, dtype=np.float64)
    total_ms = np.zeros(len(edges) - 1, dtype=np.float64)
    if len(ordered) < 2:
        for event in ordered:
            if event.team_id == team_id:
                index = int(
                    np.clip(
                        np.digitize(clock_minutes(event), edges, right=False) - 1,
                        0,
                        len(team_ms) - 1,
                    )
                )
                team_ms[index] += 1.0
                total_ms[index] += 1.0
        percents = (
            np.divide(team_ms, total_ms, out=np.zeros_like(team_ms), where=total_ms > 0) * 100.0
        )
        return [
            TemporalBin(
                start_minute=int(edges[index]),
                end_minute=int(edges[index + 1]),
                label=f"{int(edges[index]):02d}–{int(edges[index + 1]):02d}",
                value=round(float(percents[index]), 1),
            )
            for index in range(len(percents))
        ]

    starts = np.fromiter(
        (clock_minutes(event) for event in ordered[:-1]), dtype=np.float64, count=len(ordered) - 1
    )
    ends = np.fromiter(
        (clock_minutes(event) for event in ordered[1:]), dtype=np.float64, count=len(ordered) - 1
    )
    durations = np.maximum(ends - starts, 0.0)
    owners = np.fromiter(
        (1.0 if event.team_id == team_id else 0.0 for event in ordered[:-1]),
        dtype=np.float64,
        count=len(ordered) - 1,
    )
    bin_index = np.clip(np.digitize(starts, edges, right=False) - 1, 0, len(team_ms) - 1)
    np.add.at(total_ms, bin_index, durations)
    np.add.at(team_ms, bin_index, durations * owners)
    percents = np.divide(team_ms, total_ms, out=np.zeros_like(team_ms), where=total_ms > 0) * 100.0
    return [
        TemporalBin(
            start_minute=int(edges[index]),
            end_minute=int(edges[index + 1]),
            label=f"{int(edges[index]):02d}–{int(edges[index + 1]):02d}",
            value=round(float(percents[index]), 1),
        )
        for index in range(len(percents))
    ]


def detect_pass_strings(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
) -> PassStringSummary:
    """Count sequential successful team passes that end at a turnover.

    A string grows while the same team completes pass-like events. It breaks
    on an unsuccessful pass, a tagged turnover, or an opponent on-ball action.

    Args:
        events: Tagged match events, any order.
        team_id: When set, only strings belonging to this team are returned.

    Returns:
        Length histogram plus headline totals.
    """

    ordered = sorted(
        events, key=lambda item: (item.period, clock_minutes(item), str(item.event_id))
    )
    frequencies: dict[int, int] = {}
    current_team: UUID | None = None
    current_length = 0
    total_passes = 0
    longest = 0

    def _close() -> None:
        nonlocal current_length, current_team, total_passes, longest
        if current_length <= 0:
            current_team = None
            return
        if team_id is None or current_team == team_id:
            frequencies[current_length] = frequencies.get(current_length, 0) + 1
            total_passes += current_length
            if current_length > longest:
                longest = current_length
        current_length = 0
        current_team = None

    for event in ordered:
        is_pass = _is_pass(event)
        if is_pass and event.successful:
            if current_team is not None and event.team_id != current_team:
                _close()
            current_team = event.team_id
            current_length += 1
            continue
        if is_pass and not event.successful:
            if current_team is not None and event.team_id != current_team:
                _close()
            else:
                _close()
            continue
        if event.event_type in TURNOVER_EVENT_TYPES:
            _close()
            continue
        if current_team is not None and event.team_id != current_team:
            _close()

    _close()
    total_strings = sum(frequencies.values())
    rows = [
        PassStringLengthCount(
            length=length,
            count=count,
            share=round(count / total_strings, 4) if total_strings else 0.0,
        )
        for length, count in sorted(frequencies.items())
    ]
    return PassStringSummary(
        team_id=team_id,
        total_strings=total_strings,
        total_passes=total_passes,
        longest_string=longest,
        length_frequencies=rows,
    )


def temporal_breakdown(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    max_minute: int = DEFAULT_MATCH_MINUTES,
) -> TemporalBreakdown:
    """Bundle 5-minute pass counts, 15-minute possession, and pass strings."""

    possession_team = team_id
    possession_bins: list[TemporalBin] = []
    if possession_team is not None:
        possession_bins = possession_pct_per_15_minute_segment(
            events, team_id=possession_team, max_minute=max_minute
        )
    return TemporalBreakdown(
        team_id=team_id,
        player_id=player_id,
        passes_per_5_minutes=passes_per_5_minute_period(
            events, team_id=team_id, player_id=player_id, max_minute=max_minute
        ),
        possession_pct_per_15_minutes=possession_bins,
        pass_strings=detect_pass_strings(events, team_id=team_id),
    )
