"""Tests for video-sync anchors and AutoData Advanced playlist routes."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from api.main import create_app
from data_models.events import EventType, MatchEvent, ShotOutcome
from data_models.video_sync import (
    ShotHighlightKind,
    TimeFrame,
    build_playlist_panel,
    highlight_kind,
    video_anchor_from_event,
)
from tests.fakes import InMemoryProfileStore


def _shot(
    *,
    match_id,
    team_id,
    player_id,
    minute: int,
    period: int = 1,
    outcome: ShotOutcome,
    is_goal: bool = False,
) -> MatchEvent:
    return MatchEvent(
        match_id=match_id,
        team_id=team_id,
        player_id=player_id,
        period=period,
        minute=minute,
        event_type=EventType.GOAL if is_goal else EventType.SHOT,
        x=88.0,
        y=50.0,
        successful=outcome is ShotOutcome.ON_TARGET,
        is_goal=is_goal,
        shot_outcome=outcome,
        video_timestamp_ms=minute * 60_000,
        clip_url=f"https://clips.example/{minute}",
    )


def test_video_anchor_is_required_and_clickable() -> None:
    event = _shot(
        match_id=uuid4(),
        team_id=uuid4(),
        player_id=uuid4(),
        minute=23,
        outcome=ShotOutcome.ON_TARGET,
        is_goal=True,
    )
    anchor = video_anchor_from_event(event)
    assert anchor.video_timestamp_ms == 1_380_000
    assert anchor.clip_url.startswith("https://clips.example/")
    assert highlight_kind(event) == ShotHighlightKind.GOAL.value


def test_playlist_filters_shot_subtypes_and_half() -> None:
    match_id = uuid4()
    team_id = uuid4()
    player_id = uuid4()
    events = [
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=12,
            outcome=ShotOutcome.ON_TARGET,
            is_goal=True,
        ),
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=33,
            outcome=ShotOutcome.ON_TARGET,
        ),
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=40,
            outcome=ShotOutcome.BLOCKED,
        ),
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=70,
            period=2,
            outcome=ShotOutcome.MISSED,
        ),
    ]
    first_half_goals = build_playlist_panel(
        match_id,
        events,
        team_id=team_id,
        player_id=player_id,
        time_frame=TimeFrame.FIRST_HALF,
        event_type="goal",
    )
    assert first_half_goals.total_clips == 1
    assert first_half_goals.clips[0].highlight_kind == "goal"
    assert first_half_goals.clips[0].video_timestamp_ms == 720_000

    saved = build_playlist_panel(match_id, events, event_type="shot_saved")
    blocked = build_playlist_panel(match_id, events, event_type="shot_blocked")
    missed = build_playlist_panel(match_id, events, event_type="shot_off_target")
    assert saved.total_clips == 1
    assert blocked.total_clips == 1
    assert missed.total_clips == 1
    assert missed.clips[0].period == 2


def test_event_playlist_route_round_trips_filters() -> None:
    store = InMemoryProfileStore()
    application = create_app(aggregator=store)
    match_id = uuid4()
    team_id = uuid4()
    player_id = uuid4()
    events = [
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=18,
            outcome=ShotOutcome.ON_TARGET,
            is_goal=True,
        ).model_dump(mode="json"),
        _shot(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            minute=22,
            outcome=ShotOutcome.BLOCKED,
        ).model_dump(mode="json"),
    ]
    with TestClient(application) as client:
        posted = client.post(f"/api/v1/matches/{match_id}/events", json={"events": events})
        assert posted.status_code == 200
        assert posted.json()["upserted"] == 2
        playlist = client.get(
            f"/api/v1/matches/{match_id}/events",
            params={
                "team_id": str(team_id),
                "player_id": str(player_id),
                "time_frame": "full_game",
                "event_type": "goal",
            },
        )
        assert playlist.status_code == 200
        body = playlist.json()
        assert body["total_clips"] == 1
        clip = body["clips"][0]
        assert clip["highlight_kind"] == "goal"
        assert clip["video_timestamp_ms"] == 18 * 60_000
        assert clip["clip_url"].startswith("https://clips.example/")
        spatial = client.get(f"/api/v1/matches/{match_id}/analytics/spatial")
        temporal = client.get(
            f"/api/v1/matches/{match_id}/analytics/temporal",
            params={"team_id": str(team_id)},
        )
        assert spatial.status_code == 200
        assert temporal.status_code == 200
        assert temporal.json()["passes_per_5_minutes"]
