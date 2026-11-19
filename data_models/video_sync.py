"""AutoData Advanced video-sync anchors and Spiideo-style playlist panels.

Every tagged :class:`~data_models.events.MatchEvent` carries a millisecond
seek offset and a clip URL. This module turns a filtered event list into a
playlist JSON document: clicking a stat row seeks the video player to the
matching highlight.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Final
from uuid import UUID

from pydantic import Field, field_validator

from data_models.events import EventType, MatchEvent, ShotOutcome
from data_models.player_stats import StrictModel

DEFAULT_CLIP_DURATION_MS: Final[int] = 8_000
GOAL_CLIP_DURATION_MS: Final[int] = 12_000
PASS_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    {EventType.PASS, EventType.CROSS, EventType.CUTBACK, EventType.ASSIST}
)
SHOT_EVENT_TYPES: Final[frozenset[EventType]] = frozenset({EventType.SHOT, EventType.GOAL})


class TimeFrame(StrEnum):
    """Match window used by AutoData Advanced event filters."""

    FULL_GAME = "full_game"
    FIRST_HALF = "first_half"
    SECOND_HALF = "second_half"


class ShotHighlightKind(StrEnum):
    """Shot subtypes exposed as independent playlist filters."""

    GOAL = "goal"
    SHOT_SAVED = "shot_saved"
    SHOT_BLOCKED = "shot_blocked"
    SHOT_OFF_TARGET = "shot_off_target"


class VideoSyncAnchor(StrictModel):
    """Clickable video coordinate for one tagged event.

    Attributes:
        video_timestamp_ms: Seek offset from the start of the match video.
        clip_url: URL the player loads when the row is clicked.
        duration_ms: Highlight window centred on the timestamp.
    """

    video_timestamp_ms: int = Field(ge=0, description="Seek offset in milliseconds.")
    clip_url: str = Field(min_length=1, max_length=2048, description="Highlight clip URL.")
    duration_ms: int = Field(
        default=DEFAULT_CLIP_DURATION_MS,
        ge=250,
        le=120_000,
        description="Clip duration in milliseconds.",
    )

    @field_validator("clip_url")
    @classmethod
    def clip_url_is_not_blank(cls, value: str) -> str:
        """Reject whitespace-only clip URLs."""

        stripped = value.strip()
        if not stripped:
            raise ValueError("clip_url is required for a video sync anchor.")
        return stripped


class PlaylistFilters(StrictModel):
    """Query filters that produced a playlist panel."""

    team_id: UUID | None = None
    player_id: UUID | None = None
    time_frame: TimeFrame = TimeFrame.FULL_GAME
    event_type: str | None = None


class PlaylistClip(StrictModel):
    """One row in a Spiideo-style highlight panel."""

    event_id: UUID
    match_id: UUID
    team_id: UUID
    player_id: UUID | None = None
    event_type: EventType
    highlight_kind: str = Field(min_length=1)
    period: int = Field(ge=1, le=5)
    minute: int = Field(ge=0, le=150)
    second: int = Field(ge=0, le=59)
    clock_label: str
    video_timestamp_ms: int = Field(ge=0)
    clip_url: str = Field(min_length=1, max_length=2048)
    duration_ms: int = Field(ge=250, le=120_000)
    label: str = Field(min_length=1)
    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    end_x: float | None = Field(default=None, ge=0.0, le=100.0)
    end_y: float | None = Field(default=None, ge=0.0, le=100.0)
    successful: bool = True
    is_goal: bool = False
    shot_outcome: ShotOutcome | None = None
    sequence_index: int = Field(default=0, ge=0)


class PlaylistPanel(StrictModel):
    """Playlist JSON consumed by the video player side panel."""

    match_id: UUID
    title: str
    filters: PlaylistFilters
    total_clips: int = Field(ge=0)
    clips: list[PlaylistClip]


def clock_minutes(event: MatchEvent) -> float:
    """Return the match clock as a fractional minute."""

    if event.video_timestamp_ms > 0:
        return event.video_timestamp_ms / 60_000.0
    return float(event.minute) + (event.second / 60.0)


def resolve_video_timestamp_ms(event: MatchEvent) -> int:
    """Return the explicit seek offset, or derive it from the match clock."""

    if event.video_timestamp_ms > 0:
        return event.video_timestamp_ms
    return (event.minute * 60 + event.second) * 1000


def resolve_clip_url(event: MatchEvent) -> str:
    """Return a stored clip URL, or a seekable match-video fallback."""

    stored = event.clip_url.strip()
    if stored:
        return stored
    stamp = resolve_video_timestamp_ms(event)
    return f"/video/matches/{event.match_id}?t={stamp}&event={event.event_id}"


def highlight_kind(event: MatchEvent) -> str:
    """Map an event onto a playlist filter key, splitting shots by outcome."""

    if event.is_goal or event.event_type is EventType.GOAL:
        return ShotHighlightKind.GOAL.value
    if event.event_type is EventType.SHOT:
        if event.shot_outcome is ShotOutcome.ON_TARGET:
            return ShotHighlightKind.SHOT_SAVED.value
        if event.shot_outcome is ShotOutcome.BLOCKED:
            return ShotHighlightKind.SHOT_BLOCKED.value
        return ShotHighlightKind.SHOT_OFF_TARGET.value
    return event.event_type.value


def event_in_time_frame(event: MatchEvent, time_frame: TimeFrame) -> bool:
    """Return whether ``event`` belongs to ``time_frame``."""

    if time_frame is TimeFrame.FULL_GAME:
        return True
    if time_frame is TimeFrame.FIRST_HALF:
        return event.period == 1
    return event.period == 2


def matches_event_type_filter(event: MatchEvent, event_type: str | None) -> bool:
    """Return whether ``event`` matches a canonical type or shot subtype."""

    if event_type is None or not event_type.strip():
        return True
    key = event_type.strip().lower().replace(" ", "_").replace("-", "_")
    if key in {kind.value for kind in ShotHighlightKind}:
        return highlight_kind(event) == key
    if key == EventType.SHOT.value:
        return event.event_type in SHOT_EVENT_TYPES or event.is_goal
    if key == EventType.GOAL.value:
        return event.is_goal or event.event_type is EventType.GOAL
    return event.event_type.value == key


def filter_events(
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    time_frame: TimeFrame = TimeFrame.FULL_GAME,
    event_type: str | None = None,
) -> list[MatchEvent]:
    """Apply AutoData Advanced multi-variable filters to an event list."""

    filtered: list[MatchEvent] = []
    for event in events:
        if team_id is not None and event.team_id != team_id:
            continue
        if player_id is not None and event.player_id != player_id:
            continue
        if not event_in_time_frame(event, time_frame):
            continue
        if not matches_event_type_filter(event, event_type):
            continue
        filtered.append(event)
    filtered.sort(
        key=lambda item: (
            item.period,
            item.minute,
            item.second,
            resolve_video_timestamp_ms(item),
            str(item.event_id),
        )
    )
    return filtered


def _clock_label(event: MatchEvent) -> str:
    return f"{event.minute:02d}:{event.second:02d}"


def _clip_label(event: MatchEvent) -> str:
    kind = highlight_kind(event).replace("_", " ").title()
    return f"{kind} · {_clock_label(event)}"


def _clip_duration_ms(event: MatchEvent) -> int:
    if event.is_goal or event.event_type is EventType.GOAL:
        return GOAL_CLIP_DURATION_MS
    return DEFAULT_CLIP_DURATION_MS


def clip_from_event(event: MatchEvent, *, sequence_index: int) -> PlaylistClip:
    """Project a tagged event onto a clickable playlist row."""

    kind = highlight_kind(event)
    return PlaylistClip(
        event_id=event.event_id,
        match_id=event.match_id,
        team_id=event.team_id,
        player_id=event.player_id,
        event_type=event.event_type,
        highlight_kind=kind,
        period=event.period,
        minute=event.minute,
        second=event.second,
        clock_label=_clock_label(event),
        video_timestamp_ms=resolve_video_timestamp_ms(event),
        clip_url=resolve_clip_url(event),
        duration_ms=_clip_duration_ms(event),
        label=_clip_label(event),
        x=event.x,
        y=event.y,
        end_x=event.end_x,
        end_y=event.end_y,
        successful=event.successful,
        is_goal=event.is_goal or event.event_type is EventType.GOAL,
        shot_outcome=event.shot_outcome,
        sequence_index=sequence_index,
    )


def build_playlist_panel(
    match_id: UUID,
    events: Sequence[MatchEvent],
    *,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    time_frame: TimeFrame = TimeFrame.FULL_GAME,
    event_type: str | None = None,
) -> PlaylistPanel:
    """Build a Spiideo-style panel from filtered match events.

    Args:
        match_id: Parent match.
        events: Candidate events, typically all tags for ``match_id``.
        team_id: Optional team filter.
        player_id: Optional player filter.
        time_frame: Full game or a single half.
        event_type: Canonical event type or shot subtype.

    Returns:
        A playlist document ordered by match clock, ready for a video player.
    """

    filters = PlaylistFilters(
        team_id=team_id,
        player_id=player_id,
        time_frame=time_frame,
        event_type=event_type,
    )
    selected = [
        event
        for event in filter_events(
            events,
            team_id=team_id,
            player_id=player_id,
            time_frame=time_frame,
            event_type=event_type,
        )
        if event.match_id == match_id
    ]
    clips = [clip_from_event(event, sequence_index=index) for index, event in enumerate(selected)]
    title_parts = ["Highlights"]
    if event_type:
        title_parts = [event_type.replace("_", " ").title()]
    if time_frame is not TimeFrame.FULL_GAME:
        title_parts.append(time_frame.value.replace("_", " ").title())
    return PlaylistPanel(
        match_id=match_id,
        title=" · ".join(title_parts),
        filters=filters,
        total_clips=len(clips),
        clips=clips,
    )


def video_anchor_from_event(event: MatchEvent) -> VideoSyncAnchor:
    """Build a required video-sync anchor from a tagged event."""

    return VideoSyncAnchor(
        video_timestamp_ms=resolve_video_timestamp_ms(event),
        clip_url=resolve_clip_url(event),
        duration_ms=_clip_duration_ms(event),
    )
