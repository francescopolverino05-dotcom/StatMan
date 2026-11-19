"""Real-time aggregation of tagged match events into player-match pillars."""

from __future__ import annotations

from uuid import UUID

from config.pitch_config import PenaltyBox, PitchThird
from data_models.events import EventType, MatchEvent, PassLengthBand, ShotOutcome, TaggedMatchEvent
from data_models.player_stats import DistributionStats, PlayerMatchStats


class PlayerStatsCollector:
    """Accumulate :class:`PlayerMatchStats` from a live event stream.

    The collector is immutable at the stats-row level: each :meth:`apply` call
    returns a new :class:`PlayerMatchStats` snapshot. Callers that tag events
    for several players should keep one collector per ``(match_id, player_id)``.

    Args:
        stats: Initial player-match row, typically empty pillars at kick-off.
    """

    def __init__(self, stats: PlayerMatchStats) -> None:
        self._stats = stats

    @property
    def stats(self) -> PlayerMatchStats:
        """Latest accumulated player-match snapshot."""

        return self._stats

    def apply(self, event: MatchEvent) -> PlayerMatchStats:
        """Fold one tagged event into the current snapshot.

        Events whose ``player_id`` does not match this row are ignored so a
        match-wide feed can be broadcast to every collector.

        Args:
            event: Raw on-ball tag on the 0–100 grid.

        Returns:
            The updated :class:`PlayerMatchStats` snapshot.

        Raises:
            ValueError: If the event belongs to a different match or team.
        """

        if event.match_id != self._stats.match_id:
            raise ValueError("Event match_id does not match this collector.")
        if event.team_id != self._stats.team_id:
            raise ValueError("Event team_id does not match this collector.")
        if event.player_id is None or event.player_id != self._stats.player_id:
            return self._stats

        tagged = TaggedMatchEvent.from_event(event)
        updated = self._apply_tagged(tagged)
        self._stats = updated
        return updated

    def _apply_tagged(self, event: TaggedMatchEvent) -> PlayerMatchStats:
        offensive = self._stats.offensive
        defensive = self._stats.defensive
        distribution = self._stats.distribution
        third = event.start_third.value
        inside_attacking_box = event.start_penalty_box is PenaltyBox.ATTACKING

        if event.event_type in {EventType.SHOT, EventType.GOAL}:
            if event.shot_outcome is None:
                raise ValueError("Shot events require shot_outcome.")
            offensive = offensive.record_shot(
                inside_penalty_area=inside_attacking_box,
                on_target=event.shot_outcome is ShotOutcome.ON_TARGET,
                blocked=event.shot_outcome is ShotOutcome.BLOCKED,
                missed=event.shot_outcome is ShotOutcome.MISSED,
                is_goal=event.is_goal or event.event_type is EventType.GOAL,
                is_penalty=event.is_penalty,
            )
        elif event.event_type is EventType.ASSIST:
            offensive = offensive.record_assist()
            distribution = self._record_pass(distribution, event, is_assist=True)
        elif event.event_type is EventType.OFFSIDE:
            offensive = offensive.record_offside()
        elif event.event_type is EventType.FREE_KICK:
            offensive = offensive.record_freekick()
            if event.end_location is not None:
                distribution = self._record_pass(distribution, event)
        elif event.event_type is EventType.CORNER:
            offensive = offensive.record_corner()
            if event.end_location is not None:
                distribution = self._record_pass(distribution, event)
        elif event.event_type is EventType.THROW_IN:
            offensive = offensive.record_throw_in()
            if event.end_location is not None:
                distribution = self._record_pass(distribution, event)
        elif event.event_type in {EventType.PASS, EventType.CROSS, EventType.CUTBACK}:
            distribution = self._record_pass(distribution, event)
        elif event.event_type is EventType.AERIAL_DUEL:
            defensive = defensive.record_aerial_duel(succeeded=event.successful)
        elif event.event_type is EventType.GROUND_DUEL:
            defensive = defensive.record_ground_duel(succeeded=event.successful)
        elif event.event_type is EventType.BLOCK_SHOT:
            defensive = defensive.record_block("shots")
        elif event.event_type is EventType.BLOCK_CROSS:
            defensive = defensive.record_block("crosses")
        elif event.event_type is EventType.BLOCK_PASS:
            defensive = defensive.record_block("passes")
        elif event.event_type is EventType.FOUL_COMMITTED:
            defensive = defensive.record_foul(won=False)
        elif event.event_type is EventType.FOUL_WON:
            defensive = defensive.record_foul(won=True)
        elif event.event_type is EventType.INTERCEPTION:
            defensive = defensive.record_interception(third)
        elif event.event_type is EventType.BALL_RECOVERY:
            defensive = defensive.record_recovery(third)
        elif event.event_type is EventType.BALL_LOST:
            defensive = defensive.record_ball_lost(third)
        elif event.event_type is EventType.YELLOW_CARD:
            defensive = defensive.record_yellow_card()
        elif event.event_type is EventType.RED_CARD:
            defensive = defensive.record_red_card()
        elif event.event_type is EventType.GOAL_CONCEDED:
            defensive = defensive.record_goal_against()

        clock_minutes = float(event.minute) + (event.second / 60.0)
        if clock_minutes > offensive.minutes:
            offensive = offensive.with_minutes(clock_minutes)

        return self._stats.replace_pillars(
            offensive=offensive,
            defensive=defensive,
            distribution=distribution,
        )

    @staticmethod
    def _record_pass(
        distribution: DistributionStats,
        event: TaggedMatchEvent,
        *,
        is_assist: bool = False,
    ) -> DistributionStats:
        """Apply a pass-like event onto distribution metrics."""

        band = event.pass_band.value if event.pass_band is not None else PassLengthBand.SHORT.value
        start_third = event.start_third.value
        into_final = False
        direction: str | None = None
        if event.end_location is not None:
            into_final = (
                event.start_third is not PitchThird.FINAL
                and event.end_location.third is PitchThird.FINAL
            )
            direction = _pass_direction(
                event.start_location.x,
                event.start_location.y,
                event.end_location.x,
                event.end_location.y,
            )
        return distribution.record_pass(
            succeeded=event.successful or is_assist,
            band=band,
            into_penalty_area=event.end_in_attacking_penalty_area,
            is_cross=event.event_type is EventType.CROSS,
            is_cutback=event.event_type is EventType.CUTBACK,
            is_progressive=event.is_progressive,
            start_third=start_third,
            into_final_third=into_final,
            direction=direction,
        )


def _pass_direction(start_x: float, start_y: float, end_x: float, end_y: float) -> str:
    """Classify a pass as forward, sideways, or backward on the attacking frame."""

    dx = end_x - start_x
    dy = end_y - start_y
    if abs(dx) >= abs(dy):
        return "forward" if dx >= 0 else "backward"
    return "sideways"


def new_collector(
    *,
    match_id: UUID,
    player_id: UUID,
    team_id: UUID,
    jersey_number: int | None = None,
    position: str = "",
    player_name: str = "",
) -> PlayerStatsCollector:
    """Construct a zeroed collector for a player at kick-off.

    Args:
        match_id: Parent match identifier.
        player_id: Player being tracked.
        team_id: Team the player represents in this match.
        jersey_number: Shirt number, if known.
        position: Primary position code (e.g. ``CM``).
        player_name: Display name used on the dashboard.
    """

    return PlayerStatsCollector(
        PlayerMatchStats(
            match_id=match_id,
            player_id=player_id,
            team_id=team_id,
            jersey_number=jersey_number,
            player_name=player_name,
            position=position,
        )
    )
