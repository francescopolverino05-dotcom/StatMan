"""Tests for AutoData Advanced spatial zones and pass-success sectors."""

from __future__ import annotations

from uuid import uuid4

from analytics.spatial_zones import (
    FinalThirdEntryZone,
    PassQuadrant,
    PitchChannel,
    map_to_play_zone,
    spatial_breakdown,
)
from config.pitch_config import PitchThird
from data_models.events import EventType, MatchEvent


def test_map_to_play_zone_assigns_third_channel_and_quadrant() -> None:
    defensive_left = map_to_play_zone(10.0, 10.0)
    assert defensive_left.third is PitchThird.DEFENSIVE
    assert defensive_left.channel is PitchChannel.LEFT
    assert defensive_left.quadrant is PassQuadrant.DEFENSIVE_LEFT
    attacking_right = map_to_play_zone(90.0, 90.0)
    assert attacking_right.third is PitchThird.FINAL
    assert attacking_right.channel is PitchChannel.RIGHT
    assert attacking_right.quadrant is PassQuadrant.ATTACKING_RIGHT
    assert attacking_right.final_third_entry_zone is FinalThirdEntryZone.RIGHT_CHANNEL
    assert attacking_right.x_pct == 90.0


def test_sector_pass_rates_and_final_third_entries() -> None:
    match_id = uuid4()
    team_id = uuid4()
    events = [
        MatchEvent(
            match_id=match_id,
            team_id=team_id,
            player_id=uuid4(),
            minute=20,
            event_type=EventType.PASS,
            x=50.0,
            y=50.0,
            end_x=80.0,
            end_y=50.0,
            successful=True,
            video_timestamp_ms=1_200_000,
            clip_url="https://clips.example/entry",
        ),
        MatchEvent(
            match_id=match_id,
            team_id=team_id,
            player_id=uuid4(),
            minute=21,
            event_type=EventType.PASS,
            x=50.0,
            y=50.0,
            end_x=82.0,
            end_y=15.0,
            successful=False,
            video_timestamp_ms=1_260_000,
            clip_url="https://clips.example/missed-entry",
        ),
        MatchEvent(
            match_id=match_id,
            team_id=team_id,
            player_id=uuid4(),
            minute=22,
            event_type=EventType.BALL_LOST,
            x=70.0,
            y=30.0,
            video_timestamp_ms=1_320_000,
            clip_url="https://clips.example/lost",
        ),
        MatchEvent(
            match_id=match_id,
            team_id=team_id,
            player_id=uuid4(),
            minute=23,
            event_type=EventType.BALL_RECOVERY,
            x=25.0,
            y=60.0,
            video_timestamp_ms=1_380_000,
            clip_url="https://clips.example/won",
        ),
    ]
    report = spatial_breakdown(events, team_id=team_id)
    populated = [row for row in report.sectors if row.attempts]
    assert populated
    assert abs(sum(row.play_share for row in populated) - 1.0) < 1e-6
    centre_entries = next(
        row for row in report.final_third_entries if row.zone is FinalThirdEntryZone.CENTRE
    )
    left_entries = next(
        row for row in report.final_third_entries if row.zone is FinalThirdEntryZone.LEFT_CHANNEL
    )
    assert centre_entries.attempts == 1
    assert centre_entries.success_rate == 1.0
    assert left_entries.attempts == 1
    assert left_entries.success_rate == 0.0
    assert len(report.balls_lost) == 1
    assert len(report.balls_recovered) == 1
    assert report.balls_lost[0].quadrant is PassQuadrant.ATTACKING_LEFT
