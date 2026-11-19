"""In-memory player-profile and match-event store used by API tests."""

from __future__ import annotations

from uuid import UUID

from data_models.events import MatchEvent
from data_models.player_stats import PlayerMatchProfile


class InMemoryProfileStore:
    """Test double that records upserts without PostgreSQL."""

    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], PlayerMatchProfile] = {}
        self.events: dict[UUID, MatchEvent] = {}

    async def upsert_player_profile(
        self,
        match_id: UUID,
        profile: PlayerMatchProfile,
    ) -> UUID:
        if profile.match_id != match_id:
            raise ValueError("profile.match_id does not match argument match_id.")
        stored = PlayerMatchProfile.from_stats(profile)
        self.rows[(profile.player_id, match_id)] = stored
        return stored.stats_id

    async def fetch_player_profile(
        self,
        player_id: UUID,
        match_id: UUID,
    ) -> PlayerMatchProfile | None:
        return self.rows.get((player_id, match_id))

    async def upsert_match_events(
        self,
        match_id: UUID,
        events: list[MatchEvent] | tuple[MatchEvent, ...],
    ) -> int:
        for event in events:
            if event.match_id != match_id:
                raise ValueError("event.match_id does not match argument match_id.")
            self.events[event.event_id] = event
        return len(events)

    async def fetch_match_events(
        self,
        match_id: UUID,
        *,
        team_id: UUID | None = None,
        player_id: UUID | None = None,
        period: int | None = None,
    ) -> list[MatchEvent]:
        loaded: list[MatchEvent] = []
        for event in self.events.values():
            if event.match_id != match_id:
                continue
            if team_id is not None and event.team_id != team_id:
                continue
            if player_id is not None and event.player_id != player_id:
                continue
            if period is not None and event.period != period:
                continue
            loaded.append(event)
        loaded.sort(key=lambda item: (item.period, item.minute, item.second, str(item.event_id)))
        return loaded
