"""Tests for PostgreSQL DDL and the async player-profile aggregator."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from data_models.player_stats import (
    AttemptSplit,
    DefensiveStats,
    DistributionStats,
    OffensiveStats,
    PassLocationStats,
    PlayerMatchProfile,
    PlayerMatchStats,
)
from storage.db_aggregator import (
    FETCH_PLAYER_PROFILE_SQL,
    SCHEMA_PATH,
    UPSERT_PLAYER_PROFILE_SQL,
    DatabaseAggregator,
    PlayerProfilePersistenceError,
    StorageError,
    _bind_profile_arguments,
    _to_jsonb_payload,
    normalize_asyncpg_dsn,
    split_sql_statements,
)


def _sample_profile(**overrides: object) -> PlayerMatchProfile:
    match_id = overrides.get("match_id", uuid4())
    player_id = overrides.get("player_id", uuid4())
    team_id = overrides.get("team_id", uuid4())
    payload: dict[str, object] = {
        "match_id": match_id,
        "player_id": player_id,
        "team_id": team_id,
        "jersey_number": 10,
        "position": "ST",
        "offensive": OffensiveStats(
            minutes=67.5,
            goals=1,
            assists=1,
            total_shots=4,
            shots_on_target=2,
            blocked_shots=1,
            missed_shots=1,
            shots_inside_penalty_area=3,
            shots_outside_penalty_area=1,
        ),
        "defensive": DefensiveStats(
            aerial_duels=AttemptSplit(success=2, total=3),
            ground_duels=AttemptSplit(success=4, total=5),
        ),
        "distribution": DistributionStats(
            passes=AttemptSplit(success=18, total=22),
            crosses=AttemptSplit(success=1, total=3),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=10, total=12),
                medium=AttemptSplit(success=6, total=7),
                long=AttemptSplit(success=2, total=3),
                into_penalty_area=AttemptSplit(success=2, total=4),
            ),
        ),
        "collected_at": datetime(2026, 9, 18, 15, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return PlayerMatchProfile.model_validate(payload)


class _FakeTransaction:
    async def __aenter__(self) -> _FakeTransaction:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchval_result: Any = None
        self.fetchrow_result: Any = None
        self.fail_on: str | None = None

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, query: str, *args: Any) -> str:
        self.statements.append((query, args))
        if self.fail_on and self.fail_on in query:
            raise OSError("forced failure")
        return "INSERT 0 1"

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.statements.append((query, args))
        if self.fail_on and self.fail_on in query:
            raise OSError("forced failure")
        return self.fetchval_result

    async def fetchrow(self, query: str, *args: Any) -> Any:
        self.statements.append((query, args))
        if self.fail_on and self.fail_on in query:
            raise OSError("forced failure")
        return self.fetchrow_result


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.closed = False

    @asynccontextmanager
    async def acquire(self) -> Any:
        yield self.connection

    async def close(self) -> None:
        self.closed = True


def test_schema_defines_hybrid_tables_and_gin_indexes() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = split_sql_statements(sql)
    joined = "\n".join(statements).lower()

    assert "create table if not exists matches" in joined
    assert "create table if not exists player_match_stats" in joined
    assert "primary key (player_id, match_id)" in joined
    assert "using gin (defensive)" in joined
    assert "using gin (distribution)" in joined
    for column in (
        "goals",
        "assists",
        "total_shots",
        "shots_on_target",
        "blocked_shots",
        "missed_shots",
        "shots_inside_penalty_area",
        "shots_outside_penalty_area",
        "offsides",
        "freekicks",
        "corners",
        "minutes",
        "player_name",
        "penalty_kicks",
        "throw_ins",
    ):
        assert column in joined
    assert "defensive                       jsonb" in joined
    assert "distribution                    jsonb" in joined
    assert "possession                      jsonb" in joined
    assert "using gin (possession)" in joined
    assert "create table if not exists match_events" in joined
    assert "create table if not exists video_clip_index" in joined
    assert "video_timestamp_ms" in joined
    assert "clip_url" in joined


def test_normalize_sqlalchemy_asyncpg_dsn() -> None:
    assert (
        normalize_asyncpg_dsn(
            "postgresql+asyncpg://enjoystats:enjoystats@localhost:5432/enjoystats"
        )
        == "postgresql://enjoystats:enjoystats@localhost:5432/enjoystats"
    )


def test_jsonb_payload_strips_computed_fields() -> None:
    defensive = DefensiveStats(aerial_duels=AttemptSplit(success=1, total=2))
    payload = _to_jsonb_payload(defensive)
    assert "success_rate" not in json.dumps(payload)
    assert "failed" not in payload["aerial_duels"]
    assert payload["aerial_duels"] == {"success": 1, "total": 2}
    assert "total" not in payload["blocks"]
    round_trip = DefensiveStats.model_validate(payload)
    assert round_trip.aerial_duels.success_rate == 0.5


@pytest.mark.asyncio
async def test_upsert_player_profile_maps_pillars_and_conflict_target() -> None:
    match_id = uuid4()
    profile = _sample_profile(match_id=match_id)
    connection = _FakeConnection()
    connection.fetchval_result = profile.stats_id
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))

    returned = await aggregator.upsert_player_profile(match_id, profile)

    assert returned == profile.stats_id
    assert "INSERT INTO matches" in connection.statements[0][0]
    upsert_sql, args = connection.statements[1]
    assert upsert_sql == UPSERT_PLAYER_PROFILE_SQL
    assert args[0] == profile.player_id
    assert args[1] == match_id
    assert args[7] == 67.5
    assert args[8] == 1
    assert args[9] == 1
    assert json.loads(args[21])["aerial_duels"]["success"] == 2
    assert json.loads(args[22])["passes"]["total"] == 22
    assert "success_rate" not in args[21]
    assert json.loads(args[23])["percentage"] == 0.0


@pytest.mark.asyncio
async def test_upsert_accepts_player_match_stats_snapshot() -> None:
    match_id = uuid4()
    stats = PlayerMatchStats(
        match_id=match_id,
        player_id=uuid4(),
        team_id=uuid4(),
        offensive=OffensiveStats(minutes=10.0),
    )
    connection = _FakeConnection()
    connection.fetchval_result = stats.stats_id
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))
    returned = await aggregator.upsert_player_profile(match_id, stats)
    assert returned == stats.stats_id


@pytest.mark.asyncio
async def test_upsert_rejects_mismatched_match_id() -> None:
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(_FakeConnection()))
    profile = _sample_profile()
    with pytest.raises(ValueError, match="does not match"):
        await aggregator.upsert_player_profile(uuid4(), profile)


@pytest.mark.asyncio
async def test_upsert_wraps_connection_failures() -> None:
    match_id = uuid4()
    profile = _sample_profile(match_id=match_id)
    connection = _FakeConnection()
    connection.fail_on = "INSERT INTO player_match_stats"
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))
    with pytest.raises(PlayerProfilePersistenceError, match="Unable to upsert"):
        await aggregator.upsert_player_profile(match_id, profile)


@pytest.mark.asyncio
async def test_fetch_player_profile_round_trip_mapping() -> None:
    profile = _sample_profile()
    args = _bind_profile_arguments(profile.match_id, profile)
    connection = _FakeConnection()
    connection.fetchrow_result = {
        "player_id": args[0],
        "match_id": args[1],
        "stats_id": args[2],
        "team_id": args[3],
        "jersey_number": args[4],
        "player_name": args[5],
        "position": args[6],
        "minutes": args[7],
        "goals": args[8],
        "assists": args[9],
        "total_shots": args[10],
        "shots_on_target": args[11],
        "blocked_shots": args[12],
        "missed_shots": args[13],
        "shots_inside_penalty_area": args[14],
        "shots_outside_penalty_area": args[15],
        "offsides": args[16],
        "freekicks": args[17],
        "corners": args[18],
        "penalty_kicks": args[19],
        "throw_ins": args[20],
        "defensive": args[21],
        "distribution": args[22],
        "possession": args[23],
        "collected_at": args[24],
    }
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))
    loaded = await aggregator.fetch_player_profile(profile.player_id, profile.match_id)
    assert loaded is not None
    assert loaded.stats_id == profile.stats_id
    assert loaded.offensive.goals == 1
    assert loaded.defensive.aerial_duels.total == 3
    assert loaded.distribution.passes.success == 18
    assert loaded.offensive.penalty_kicks == 0
    assert loaded.possession.percentage == 0.0
    assert FETCH_PLAYER_PROFILE_SQL in connection.statements[0][0]


@pytest.mark.asyncio
async def test_connect_required_before_upsert() -> None:
    aggregator = DatabaseAggregator("postgresql://unused")
    profile = _sample_profile()
    with pytest.raises(StorageError, match="connect"):
        await aggregator.upsert_player_profile(profile.match_id, profile)


def test_schema_file_lives_beside_aggregator() -> None:
    assert SCHEMA_PATH == Path(__file__).resolve().parents[1] / "storage" / "postgres_tables.sql"
    assert SCHEMA_PATH.is_file()


@pytest.mark.asyncio
async def test_ping_runs_select_one() -> None:
    connection = _FakeConnection()
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))
    await aggregator.ping()
    assert connection.statements[0][0] == "SELECT 1"


@pytest.mark.asyncio
async def test_ping_wraps_connection_failures() -> None:
    connection = _FakeConnection()
    connection.fail_on = "SELECT 1"
    aggregator = DatabaseAggregator("postgresql://unused", pool=_FakePool(connection))
    with pytest.raises(StorageError, match="health check"):
        await aggregator.ping()
