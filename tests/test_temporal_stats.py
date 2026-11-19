"""Tests for AutoData Advanced temporal aggregations and pass strings."""

from __future__ import annotations

from uuid import uuid4

from analytics.temporal_stats import (
    detect_pass_strings,
    passes_per_5_minute_period,
    possession_pct_per_15_minute_segment,
    temporal_breakdown,
)
from data_models.events import EventType, MatchEvent


def _pass(
    *,
    match_id,
    team_id,
    minute: int,
    successful: bool = True,
    player_id=None,
    x: float = 40.0,
    end_x: float = 55.0,
) -> MatchEvent:
    return MatchEvent(
        match_id=match_id,
        team_id=team_id,
        player_id=player_id or uuid4(),
        minute=minute,
        event_type=EventType.PASS,
        x=x,
        y=50.0,
        end_x=end_x,
        end_y=50.0,
        successful=successful,
        video_timestamp_ms=minute * 60_000,
        clip_url=f"https://clips.example/pass/{minute}",
    )


def test_passes_per_5_minutes_uses_numpy_bins() -> None:
    match_id = uuid4()
    team_id = uuid4()
    events = [
        _pass(match_id=match_id, team_id=team_id, minute=2),
        _pass(match_id=match_id, team_id=team_id, minute=4),
        _pass(match_id=match_id, team_id=team_id, minute=11),
        _pass(match_id=match_id, team_id=team_id, minute=47),
    ]
    bins = passes_per_5_minute_period(events, team_id=team_id, max_minute=50)
    by_label = {item.label: item.value for item in bins}
    assert by_label["00–05"] == 2.0
    assert by_label["10–15"] == 1.0
    assert by_label["45–50"] == 1.0
    assert by_label["05–10"] == 0.0


def test_pass_strings_break_on_turnover() -> None:
    match_id = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    events = [
        _pass(match_id=match_id, team_id=team_a, minute=1),
        _pass(match_id=match_id, team_id=team_a, minute=2),
        _pass(match_id=match_id, team_id=team_a, minute=3),
        MatchEvent(
            match_id=match_id,
            team_id=team_a,
            player_id=uuid4(),
            minute=4,
            event_type=EventType.BALL_LOST,
            x=60.0,
            y=40.0,
            video_timestamp_ms=240_000,
            clip_url="https://clips.example/lost",
        ),
        _pass(match_id=match_id, team_id=team_b, minute=5),
        _pass(match_id=match_id, team_id=team_b, minute=6, successful=False),
        _pass(match_id=match_id, team_id=team_a, minute=7),
        _pass(match_id=match_id, team_id=team_a, minute=8),
    ]
    summary = detect_pass_strings(events, team_id=team_a)
    lengths = {row.length: row.count for row in summary.length_frequencies}
    assert lengths[3] == 1
    assert lengths[2] == 1
    assert summary.longest_string == 3
    assert summary.total_strings == 2


def test_possession_15_minute_segments_split_by_team() -> None:
    match_id = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    events = [
        _pass(match_id=match_id, team_id=team_a, minute=0),
        _pass(match_id=match_id, team_id=team_a, minute=10),
        _pass(match_id=match_id, team_id=team_b, minute=12),
        _pass(match_id=match_id, team_id=team_b, minute=14),
    ]
    bins = possession_pct_per_15_minute_segment(events, team_id=team_a, max_minute=15)
    first = bins[0]
    assert first.start_minute == 0
    assert first.end_minute == 15
    assert first.value > 50.0


def test_temporal_breakdown_scales_to_one_thousand_events() -> None:
    match_id = uuid4()
    team_id = uuid4()
    events = [
        _pass(match_id=match_id, team_id=team_id, minute=index % 90, x=30.0 + (index % 10))
        for index in range(1000)
    ]
    report = temporal_breakdown(events, team_id=team_id, max_minute=90)
    assert sum(item.value for item in report.passes_per_5_minutes) == 1000.0
    assert report.pass_strings.total_passes == 1000
    assert report.pass_strings.longest_string == 1000
