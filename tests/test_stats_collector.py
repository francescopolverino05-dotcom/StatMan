"""Tests for live event-to-stats collection."""

from __future__ import annotations

from uuid import uuid4

import pytest

from analytics.stats_collector import new_collector
from data_models.events import EventType, MatchEvent, ShotOutcome


def _event(**overrides: object) -> MatchEvent:
    defaults: dict[str, object] = {
        "match_id": uuid4(),
        "team_id": uuid4(),
        "player_id": uuid4(),
        "minute": 12,
        "second": 30,
        "event_type": EventType.PASS,
        "x": 40.0,
        "y": 50.0,
        "end_x": 70.0,
        "end_y": 50.0,
        "successful": True,
    }
    defaults.update(overrides)
    return MatchEvent(**defaults)  # type: ignore[arg-type]


def test_collector_applies_shot_pass_duel_and_recovery() -> None:
    match_id = uuid4()
    team_id = uuid4()
    player_id = uuid4()
    collector = new_collector(
        match_id=match_id,
        player_id=player_id,
        team_id=team_id,
        jersey_number=9,
        position="ST",
    )

    collector.apply(
        _event(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            event_type=EventType.SHOT,
            x=92.0,
            y=50.0,
            end_x=100.0,
            end_y=50.0,
            shot_outcome=ShotOutcome.ON_TARGET,
            is_goal=True,
            minute=23,
        )
    )
    collector.apply(
        _event(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            event_type=EventType.CROSS,
            x=88.0,
            y=10.0,
            end_x=94.0,
            end_y=50.0,
            is_progressive=True,
            minute=31,
        )
    )
    collector.apply(
        _event(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            event_type=EventType.AERIAL_DUEL,
            x=20.0,
            y=50.0,
            successful=True,
            minute=40,
        )
    )
    collector.apply(
        _event(
            match_id=match_id,
            team_id=team_id,
            player_id=player_id,
            event_type=EventType.BALL_RECOVERY,
            x=15.0,
            y=40.0,
            minute=44,
        )
    )

    snapshot = collector.stats
    assert snapshot.offensive.goals == 1
    assert snapshot.offensive.total_shots == 1
    assert snapshot.offensive.shots_inside_penalty_area == 1
    assert snapshot.offensive.minutes == 44.5
    assert snapshot.distribution.passes.total == 1
    assert snapshot.distribution.crosses.total == 1
    assert snapshot.distribution.pass_locations.into_penalty_area.total == 1
    assert snapshot.defensive.aerial_duels.success == 1
    assert snapshot.defensive.ball_recoveries.defensive_third == 1
    assert snapshot.distribution.pass_directions.sideways.total == 1
    assert snapshot.distribution.pass_thirds.final_third.total == 1


def test_collector_ignores_other_players() -> None:
    match_id = uuid4()
    team_id = uuid4()
    player_id = uuid4()
    collector = new_collector(match_id=match_id, player_id=player_id, team_id=team_id)
    collector.apply(
        _event(
            match_id=match_id,
            team_id=team_id,
            player_id=uuid4(),
            event_type=EventType.SHOT,
            x=92.0,
            y=50.0,
            shot_outcome=ShotOutcome.MISSED,
        )
    )
    assert collector.stats.offensive.total_shots == 0


def test_collector_rejects_wrong_match() -> None:
    collector = new_collector(match_id=uuid4(), player_id=uuid4(), team_id=uuid4())
    with pytest.raises(ValueError, match="match_id"):
        collector.apply(_event())
