"""AutoData Advanced HTTP routes: event playlists, ingest, and analytics.

The GET event route returns Spiideo-style playlist JSON: every row is a
clickable video seek (`video_timestamp_ms` + `clip_url`). Filters cover
team, player, half vs full game, and shot subtypes (goal / saved / blocked /
off target).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import Field

from analytics.spatial_zones import SpatialBreakdown, spatial_breakdown
from analytics.temporal_stats import TemporalBreakdown, temporal_breakdown
from data_models.events import MatchEvent
from data_models.player_stats import StrictModel
from data_models.video_sync import PlaylistPanel, TimeFrame, build_playlist_panel
from storage.db_aggregator import StorageError

advanced_router = APIRouter(prefix="/api/v1", tags=["autodata-advanced"])


class MatchEventBatch(StrictModel):
    """Batch ingest payload for AutoData Advanced (up to 5,000 events)."""

    events: list[MatchEvent] = Field(min_length=1, max_length=5000)


async def get_event_store(request: Request) -> Any:
    """Resolve the process-wide aggregator used for event persistence."""

    store = getattr(request.app.state, "aggregator", None)
    if store is None:
        raise StorageError("Database aggregator is not initialized.")
    return store


def _period_for_time_frame(time_frame: TimeFrame) -> int | None:
    if time_frame is TimeFrame.FIRST_HALF:
        return 1
    if time_frame is TimeFrame.SECOND_HALF:
        return 2
    return None


async def _load_events(
    store: Any,
    match_id: UUID,
    *,
    team_id: UUID | None,
    player_id: UUID | None,
    time_frame: TimeFrame,
) -> list[MatchEvent]:
    fetch = getattr(store, "fetch_match_events", None)
    if not callable(fetch):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Event store is not available on this aggregator.",
        )
    period = _period_for_time_frame(time_frame)
    loaded = fetch(
        match_id,
        team_id=team_id,
        player_id=player_id,
        period=period,
    )
    if hasattr(loaded, "__await__"):
        loaded = await loaded
    return list(loaded)


@advanced_router.get(
    "/matches/{match_id}/events",
    response_model=PlaylistPanel,
    summary="Filtered event playlist for the video player",
)
async def get_match_event_playlist(
    match_id: UUID,
    store: Any = Depends(get_event_store),
    team_id: Annotated[UUID | None, Query(description="Restrict clips to one team.")] = None,
    player_id: Annotated[UUID | None, Query(description="Restrict clips to one player.")] = None,
    time_frame: Annotated[
        TimeFrame,
        Query(description="Full game or a single half."),
    ] = TimeFrame.FULL_GAME,
    event_type: Annotated[
        str | None,
        Query(
            description=(
                "Canonical event type, or a shot subtype: goal, shot_saved, "
                "shot_blocked, shot_off_target."
            )
        ),
    ] = None,
) -> PlaylistPanel:
    """Return clickable highlight clips for the selected filters."""

    events = await _load_events(
        store,
        match_id,
        team_id=team_id,
        player_id=player_id,
        time_frame=time_frame,
    )
    return build_playlist_panel(
        match_id,
        events,
        team_id=team_id,
        player_id=player_id,
        time_frame=time_frame,
        event_type=event_type,
    )


@advanced_router.post(
    "/matches/{match_id}/events",
    summary="Batch-upsert tagged match events (1,000+ capacity)",
)
async def ingest_match_events(
    match_id: UUID,
    batch: MatchEventBatch,
    store: Any = Depends(get_event_store),
) -> dict[str, int | str]:
    """Persist a batch of video-indexed events for a match."""

    for event in batch.events:
        if event.match_id != match_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON match_id does not match the match_id in the URL path.",
            )
    upsert = getattr(store, "upsert_match_events", None)
    if not callable(upsert):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Event store is not available on this aggregator.",
        )
    result = upsert(match_id, batch.events)
    if hasattr(result, "__await__"):
        written = await result
    else:
        written = result
    return {"match_id": str(match_id), "upserted": int(written)}


@advanced_router.get(
    "/matches/{match_id}/analytics/temporal",
    response_model=TemporalBreakdown,
    summary="Passes per 5 minutes, possession per 15 minutes, pass strings",
)
async def get_temporal_analytics(
    match_id: UUID,
    store: Any = Depends(get_event_store),
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    time_frame: TimeFrame = TimeFrame.FULL_GAME,
) -> TemporalBreakdown:
    """Return numpy-backed temporal aggregations for the match."""

    events = await _load_events(
        store,
        match_id,
        team_id=None,
        player_id=None,
        time_frame=time_frame,
    )
    return temporal_breakdown(events, team_id=team_id, player_id=player_id)


@advanced_router.get(
    "/matches/{match_id}/analytics/spatial",
    response_model=SpatialBreakdown,
    summary="Zonal pass rates, quadrants, and ball lost/recovered coordinates",
)
async def get_spatial_analytics(
    match_id: UUID,
    store: Any = Depends(get_event_store),
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    time_frame: TimeFrame = TimeFrame.FULL_GAME,
) -> SpatialBreakdown:
    """Return AutoData Advanced spatial distributions for the match."""

    events = await _load_events(
        store,
        match_id,
        team_id=None,
        player_id=None,
        time_frame=time_frame,
    )
    return spatial_breakdown(events, team_id=team_id, player_id=player_id)
