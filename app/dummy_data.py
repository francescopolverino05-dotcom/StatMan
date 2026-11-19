"""Stakeholder-preview profiles used when FastAPI is unreachable."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from uuid import UUID

from data_models.player_stats import (
    AttemptSplit,
    BallLostStats,
    BallRecoveryStats,
    BlockStats,
    DefensiveStats,
    DistributionStats,
    FoulStats,
    InterceptionStats,
    OffensiveStats,
    PassDirectionStats,
    PassLocationStats,
    PassThirdStats,
    PlayerMatchProfile,
    PossessionStats,
)

from app.metrics import PassDirections

SIM_MATCH_ID: Final[UUID] = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
SHOWCASE_MATCH_ID: Final[UUID] = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
PLAYMAKER_ID: Final[UUID] = UUID("11111111-1111-1111-1111-111111111111")
STRIKER_ID: Final[UUID] = UUID("22222222-2222-2222-2222-222222222222")
CONTROLLER_ID: Final[UUID] = UUID("44444444-4444-4444-4444-444444444444")
TEAM_ID: Final[UUID] = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

_KICKOFF = datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class PitchAction:
    """A single tagged location used by the 2D pitch plot.

    Missing ``x``/``y`` (or end coordinates on a pass) are skipped at render
    time so incomplete live tags never crash the dashboard.
    """

    event_type: str
    x: float | None
    y: float | None
    end_x: float | None = None
    end_y: float | None = None
    successful: bool = True
    is_goal: bool = False
    shot_outcome: str | None = None


def _pass(
    x: float, y: float, end_x: float, end_y: float, *, successful: bool = True
) -> PitchAction:
    return PitchAction(
        event_type="pass",
        x=x,
        y=y,
        end_x=end_x,
        end_y=end_y,
        successful=successful,
    )


def _shot(
    x: float,
    y: float,
    *,
    is_goal: bool = False,
    shot_outcome: str,
) -> PitchAction:
    return PitchAction(
        event_type="shot",
        x=x,
        y=y,
        end_x=100.0 if is_goal else None,
        end_y=50.0 if is_goal else None,
        successful=shot_outcome == "on_target",
        is_goal=is_goal,
        shot_outcome=shot_outcome,
    )


def _playmaker_actions() -> tuple[PitchAction, ...]:
    """Playmaker passes from the 5-second attacking move."""

    return (
        _pass(42.0, 48.0, 50.0, 50.0),
        _pass(50.0, 50.0, 60.0, 49.0),
        _pass(62.0, 50.0, 78.0, 52.0),
    )


def _striker_actions() -> tuple[PitchAction, ...]:
    """Striker duel location is omitted; the finish is the PA goal."""

    return (_shot(88.0, 50.0, is_goal=True, shot_outcome="on_target"),)


def _controller_actions() -> tuple[PitchAction, ...]:
    """Richer showcase scatter: mixed passes and shot outcomes."""

    return (
        _pass(38.0, 40.0, 55.0, 45.0),
        _pass(55.0, 45.0, 70.0, 30.0),
        _pass(48.0, 60.0, 46.0, 78.0, successful=False),
        _shot(91.0, 48.0, is_goal=True, shot_outcome="on_target"),
        _shot(84.0, 62.0, shot_outcome="missed"),
        _shot(79.0, 40.0, shot_outcome="on_target"),
        PitchAction(event_type="shot", x=None, y=None, shot_outcome="blocked"),
    )


def _playmaker_profile() -> PlayerMatchProfile:
    """Outcome of the 5-second mock attacking move (playmaker)."""

    return PlayerMatchProfile(
        match_id=SIM_MATCH_ID,
        player_id=PLAYMAKER_ID,
        team_id=TEAM_ID,
        jersey_number=8,
        player_name="Alex Playmaker",
        position="CAM",
        offensive=OffensiveStats(minutes=0.1, assists=1, throw_ins=1),
        defensive=DefensiveStats(
            aerial_duels=AttemptSplit(success=1, total=1),
            ground_duels=AttemptSplit(success=0, total=0),
            ball_recoveries=BallRecoveryStats(middle_third=1),
            ppda=8.5,
        ),
        distribution=DistributionStats(
            passes=AttemptSplit(success=3, total=3),
            progressive_passes=AttemptSplit(success=3, total=3),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=2, total=2),
                medium=AttemptSplit(success=1, total=1),
            ),
            pass_thirds=PassThirdStats(middle_third=AttemptSplit(success=3, total=3)),
            into_final_third=AttemptSplit(success=1, total=1),
            pass_directions=PassDirectionStats(forward=AttemptSplit(success=3, total=3)),
        ),
        possession=PossessionStats(time_minutes=0.1, percentage=2.0),
        collected_at=_KICKOFF,
    )


def _striker_profile() -> PlayerMatchProfile:
    """Outcome of the 5-second mock attacking move (striker)."""

    return PlayerMatchProfile(
        match_id=SIM_MATCH_ID,
        player_id=STRIKER_ID,
        team_id=TEAM_ID,
        jersey_number=9,
        player_name="Sam Striker",
        position="ST",
        offensive=OffensiveStats(
            minutes=0.1,
            goals=1,
            total_shots=1,
            shots_on_target=1,
            shots_inside_penalty_area=1,
        ),
        defensive=DefensiveStats(
            ground_duels=AttemptSplit(success=1, total=1),
            aerial_duels=AttemptSplit(success=0, total=1),
            ball_recoveries=BallRecoveryStats(final_third=1),
            ppda=11.2,
        ),
        distribution=DistributionStats(
            passes=AttemptSplit(success=1, total=1),
            cutbacks=AttemptSplit(success=0, total=0),
            pass_locations=PassLocationStats(short=AttemptSplit(success=1, total=1)),
            pass_thirds=PassThirdStats(final_third=AttemptSplit(success=1, total=1)),
            pass_directions=PassDirectionStats(sideways=AttemptSplit(success=1, total=1)),
        ),
        possession=PossessionStats(time_minutes=0.1, percentage=1.5),
        collected_at=_KICKOFF,
    )


def _controller_profile() -> PlayerMatchProfile:
    """Richer midfield showcase used for stakeholder walkthroughs."""

    return PlayerMatchProfile(
        match_id=SHOWCASE_MATCH_ID,
        player_id=CONTROLLER_ID,
        team_id=TEAM_ID,
        jersey_number=6,
        player_name="Chris Controller",
        position="CM",
        offensive=OffensiveStats(
            minutes=78.5,
            goals=1,
            assists=2,
            total_shots=4,
            shots_on_target=2,
            blocked_shots=1,
            missed_shots=1,
            shots_inside_penalty_area=2,
            shots_outside_penalty_area=2,
            offsides=1,
            freekicks=2,
            corners=3,
            penalty_kicks=1,
            throw_ins=4,
        ),
        defensive=DefensiveStats(
            aerial_duels=AttemptSplit(success=5, total=8),
            ground_duels=AttemptSplit(success=9, total=12),
            blocks=BlockStats(shots=2, crosses=1, passes=3),
            fouls=FoulStats(committed=2, won=3),
            interceptions=InterceptionStats(
                total=6,
                defensive_third=2,
                middle_third=3,
                final_third=1,
            ),
            ball_recoveries=BallRecoveryStats(
                defensive_third=4,
                middle_third=7,
                final_third=2,
            ),
            ball_lost=BallLostStats(
                defensive_third=2,
                middle_third=5,
                final_third=3,
            ),
            yellow_cards=1,
            red_cards=0,
            goals_against=1,
            ppda=9.4,
        ),
        distribution=DistributionStats(
            passes=AttemptSplit(success=48, total=55),
            crosses=AttemptSplit(success=3, total=6),
            cutbacks=AttemptSplit(success=2, total=3),
            progressive_passes=AttemptSplit(success=11, total=14),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=22, total=24),
                medium=AttemptSplit(success=18, total=21),
                long=AttemptSplit(success=8, total=10),
                into_penalty_area=AttemptSplit(success=5, total=8),
            ),
            pass_thirds=PassThirdStats(
                defensive_third=AttemptSplit(success=10, total=12),
                middle_third=AttemptSplit(success=24, total=28),
                final_third=AttemptSplit(success=14, total=15),
            ),
            into_final_third=AttemptSplit(success=9, total=12),
            pass_directions=PassDirectionStats(
                forward=AttemptSplit(success=24, total=28),
                sideways=AttemptSplit(success=16, total=19),
                backward=AttemptSplit(success=8, total=8),
            ),
        ),
        possession=PossessionStats(time_minutes=11.2, percentage=14.3),
        collected_at=_KICKOFF,
    )


DUMMY_PROFILES: Final[dict[tuple[UUID, UUID], PlayerMatchProfile]] = {
    (SIM_MATCH_ID, PLAYMAKER_ID): _playmaker_profile(),
    (SIM_MATCH_ID, STRIKER_ID): _striker_profile(),
    (SHOWCASE_MATCH_ID, CONTROLLER_ID): _controller_profile(),
}

DUMMY_DIRECTIONS: Final[dict[tuple[UUID, UUID], PassDirections]] = {
    (SIM_MATCH_ID, PLAYMAKER_ID): PassDirections(forward=3, sideways=0, backward=0),
    (SIM_MATCH_ID, STRIKER_ID): PassDirections(forward=0, sideways=1, backward=0),
    (SHOWCASE_MATCH_ID, CONTROLLER_ID): PassDirections(forward=28, sideways=19, backward=8),
}

DUMMY_ACTIONS: Final[dict[tuple[UUID, UUID], tuple[PitchAction, ...]]] = {
    (SIM_MATCH_ID, PLAYMAKER_ID): _playmaker_actions(),
    (SIM_MATCH_ID, STRIKER_ID): _striker_actions(),
    (SHOWCASE_MATCH_ID, CONTROLLER_ID): _controller_actions(),
}


def catalog() -> list[dict[str, object]]:
    """Sidebar options: one entry per dummy/live-known player."""

    return [
        {
            "match_id": SIM_MATCH_ID,
            "match_label": "Demo — 5s attacking move",
            "player_id": PLAYMAKER_ID,
            "player_label": "#8 CAM Playmaker",
        },
        {
            "match_id": SIM_MATCH_ID,
            "match_label": "Demo — 5s attacking move",
            "player_id": STRIKER_ID,
            "player_label": "#9 ST Striker",
        },
        {
            "match_id": SHOWCASE_MATCH_ID,
            "match_label": "Showcase — midfield controller",
            "player_id": CONTROLLER_ID,
            "player_label": "#6 CM Controller",
        },
    ]


def fallback_profile(match_id: UUID, player_id: UUID) -> PlayerMatchProfile:
    """Return a canned profile, or a clean generic row for unknown IDs."""

    cached = DUMMY_PROFILES.get((match_id, player_id))
    if cached is not None:
        return cached
    return PlayerMatchProfile(
        match_id=match_id,
        player_id=player_id,
        team_id=TEAM_ID,
        jersey_number=10,
        player_name="Preview Player",
        position="AM",
        offensive=OffensiveStats(
            minutes=64.0,
            goals=1,
            assists=1,
            total_shots=3,
            shots_on_target=2,
            missed_shots=1,
            shots_inside_penalty_area=2,
            shots_outside_penalty_area=1,
            offsides=1,
            freekicks=1,
            corners=2,
            throw_ins=3,
        ),
        defensive=DefensiveStats(
            aerial_duels=AttemptSplit(success=3, total=5),
            ground_duels=AttemptSplit(success=4, total=6),
            blocks=BlockStats(shots=1, crosses=0, passes=2),
            fouls=FoulStats(committed=1, won=2),
            interceptions=InterceptionStats(total=3, defensive_third=1, middle_third=2),
            ball_recoveries=BallRecoveryStats(
                defensive_third=2,
                middle_third=3,
                final_third=1,
            ),
            ball_lost=BallLostStats(
                defensive_third=1,
                middle_third=2,
                final_third=1,
            ),
            yellow_cards=1,
            ppda=10.1,
        ),
        distribution=DistributionStats(
            passes=AttemptSplit(success=20, total=24),
            progressive_passes=AttemptSplit(success=6, total=8),
            cutbacks=AttemptSplit(success=1, total=2),
            crosses=AttemptSplit(success=1, total=2),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=10, total=12),
                medium=AttemptSplit(success=7, total=8),
                long=AttemptSplit(success=3, total=4),
                into_penalty_area=AttemptSplit(success=2, total=3),
            ),
            pass_thirds=PassThirdStats(
                defensive_third=AttemptSplit(success=4, total=5),
                middle_third=AttemptSplit(success=11, total=13),
                final_third=AttemptSplit(success=5, total=6),
            ),
            into_final_third=AttemptSplit(success=4, total=6),
            pass_directions=PassDirectionStats(
                forward=AttemptSplit(success=10, total=12),
                sideways=AttemptSplit(success=6, total=8),
                backward=AttemptSplit(success=4, total=4),
            ),
        ),
        possession=PossessionStats(time_minutes=7.5, percentage=11.8),
    )


def fallback_directions(match_id: UUID, player_id: UUID) -> PassDirections:
    """Direction split paired with :func:`fallback_profile`."""

    cached = DUMMY_DIRECTIONS.get((match_id, player_id))
    if cached is not None:
        return cached
    return PassDirections(forward=12, sideways=8, backward=4)


def _generic_actions() -> tuple[PitchAction, ...]:
    """Preview tags used when the selected IDs have no stored locations."""

    return (
        _pass(40.0, 50.0, 58.0, 52.0),
        _shot(88.0, 50.0, is_goal=True, shot_outcome="on_target"),
        _shot(82.0, 35.0, shot_outcome="missed"),
        PitchAction(event_type="pass", x=None, y=55.0, end_x=70.0, end_y=50.0),
    )


def match_actions(
    match_id: UUID,
    player_id: UUID,
    *,
    include_generic: bool = False,
) -> tuple[PitchAction, ...]:
    """Return tagged shot/pass locations for a player-match pair.

    Args:
        match_id: Selected match UUID.
        player_id: Selected player UUID.
        include_generic: When True, unknown IDs get a small preview sequence
            that includes a missing-coordinate tag. When False, unknown IDs
            yield an empty tuple so a live profile is not decorated with
            simulated locations.
    """

    cached = DUMMY_ACTIONS.get((match_id, player_id))
    if cached is not None:
        return cached
    if include_generic:
        return _generic_actions()
    return ()


def fallback_actions(match_id: UUID, player_id: UUID) -> tuple[PitchAction, ...]:
    """Tagged shot/pass locations for the pitch plot, including a generic preview."""

    return match_actions(match_id, player_id, include_generic=True)
