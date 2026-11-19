"""Asynchronous PostgreSQL persistence for live player-match profiles.

The aggregator is the write path used during a match: tagged events are
folded into a :class:`~data_models.player_stats.PlayerMatchProfile` and
upserted on ``(player_id, match_id)`` so leaderboard columns stay current
without inserting a new row per event.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Final, Protocol, cast
from uuid import UUID

import asyncpg
from pydantic import BaseModel, ValidationError

from data_models.events import MatchEvent
from data_models.player_stats import (
    DefensiveStats,
    DistributionStats,
    OffensiveStats,
    PlayerMatchProfile,
    PlayerMatchStats,
    PossessionStats,
)
from data_models.video_sync import (
    highlight_kind,
    resolve_clip_url,
    resolve_video_timestamp_ms,
    video_anchor_from_event,
)

LOGGER = logging.getLogger(__name__)

SCHEMA_PATH: Final[Path] = Path(__file__).with_name("postgres_tables.sql")

UPSERT_PLAYER_PROFILE_SQL: Final[
    str
] = """
INSERT INTO player_match_stats (
    player_id,
    match_id,
    stats_id,
    team_id,
    jersey_number,
    player_name,
    position,
    minutes,
    goals,
    assists,
    total_shots,
    shots_on_target,
    blocked_shots,
    missed_shots,
    shots_inside_penalty_area,
    shots_outside_penalty_area,
    offsides,
    freekicks,
    corners,
    penalty_kicks,
    throw_ins,
    defensive,
    distribution,
    possession,
    collected_at,
    updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7,
    $8, $9, $10, $11, $12, $13,
    $14, $15, $16, $17, $18, $19,
    $20, $21,
    $22::jsonb, $23::jsonb, $24::jsonb, $25, NOW()
)
ON CONFLICT (player_id, match_id) DO UPDATE SET
    team_id = EXCLUDED.team_id,
    jersey_number = EXCLUDED.jersey_number,
    player_name = EXCLUDED.player_name,
    position = EXCLUDED.position,
    minutes = EXCLUDED.minutes,
    goals = EXCLUDED.goals,
    assists = EXCLUDED.assists,
    total_shots = EXCLUDED.total_shots,
    shots_on_target = EXCLUDED.shots_on_target,
    blocked_shots = EXCLUDED.blocked_shots,
    missed_shots = EXCLUDED.missed_shots,
    shots_inside_penalty_area = EXCLUDED.shots_inside_penalty_area,
    shots_outside_penalty_area = EXCLUDED.shots_outside_penalty_area,
    offsides = EXCLUDED.offsides,
    freekicks = EXCLUDED.freekicks,
    corners = EXCLUDED.corners,
    penalty_kicks = EXCLUDED.penalty_kicks,
    throw_ins = EXCLUDED.throw_ins,
    defensive = EXCLUDED.defensive,
    distribution = EXCLUDED.distribution,
    possession = EXCLUDED.possession,
    collected_at = EXCLUDED.collected_at,
    updated_at = NOW()
RETURNING stats_id
"""

ENSURE_MATCH_SQL: Final[
    str
] = """
INSERT INTO matches (match_id, status, updated_at)
VALUES ($1, 'live', NOW())
ON CONFLICT (match_id) DO NOTHING
"""

FETCH_PLAYER_PROFILE_SQL: Final[
    str
] = """
SELECT
    player_id,
    match_id,
    stats_id,
    team_id,
    jersey_number,
    player_name,
    position,
    minutes,
    goals,
    assists,
    total_shots,
    shots_on_target,
    blocked_shots,
    missed_shots,
    shots_inside_penalty_area,
    shots_outside_penalty_area,
    offsides,
    freekicks,
    corners,
    penalty_kicks,
    throw_ins,
    defensive,
    distribution,
    possession,
    collected_at
FROM player_match_stats
WHERE player_id = $1 AND match_id = $2
"""

UPSERT_MATCH_EVENT_SQL: Final[
    str
] = """
INSERT INTO match_events (
    event_id, match_id, team_id, player_id, period, minute, second,
    event_type, x, y, end_x, end_y, successful, is_goal, is_assist,
    is_progressive, is_penalty, shot_outcome, attacking_left_to_right,
    video_timestamp_ms, clip_url, recorded_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7,
    $8, $9, $10, $11, $12, $13, $14, $15,
    $16, $17, $18, $19,
    $20, $21, $22
)
ON CONFLICT (event_id) DO UPDATE SET
    match_id = EXCLUDED.match_id,
    team_id = EXCLUDED.team_id,
    player_id = EXCLUDED.player_id,
    period = EXCLUDED.period,
    minute = EXCLUDED.minute,
    second = EXCLUDED.second,
    event_type = EXCLUDED.event_type,
    x = EXCLUDED.x,
    y = EXCLUDED.y,
    end_x = EXCLUDED.end_x,
    end_y = EXCLUDED.end_y,
    successful = EXCLUDED.successful,
    is_goal = EXCLUDED.is_goal,
    is_assist = EXCLUDED.is_assist,
    is_progressive = EXCLUDED.is_progressive,
    is_penalty = EXCLUDED.is_penalty,
    shot_outcome = EXCLUDED.shot_outcome,
    attacking_left_to_right = EXCLUDED.attacking_left_to_right,
    video_timestamp_ms = EXCLUDED.video_timestamp_ms,
    clip_url = EXCLUDED.clip_url,
    recorded_at = EXCLUDED.recorded_at
"""

UPSERT_VIDEO_CLIP_INDEX_SQL: Final[
    str
] = """
INSERT INTO video_clip_index (
    event_id, match_id, team_id, player_id, event_type, highlight_kind,
    video_timestamp_ms, clip_url, duration_ms
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9
)
ON CONFLICT (event_id) DO UPDATE SET
    match_id = EXCLUDED.match_id,
    team_id = EXCLUDED.team_id,
    player_id = EXCLUDED.player_id,
    event_type = EXCLUDED.event_type,
    highlight_kind = EXCLUDED.highlight_kind,
    video_timestamp_ms = EXCLUDED.video_timestamp_ms,
    clip_url = EXCLUDED.clip_url,
    duration_ms = EXCLUDED.duration_ms
"""

FETCH_MATCH_EVENTS_SQL: Final[
    str
] = """
SELECT
    event_id, match_id, team_id, player_id, period, minute, second,
    event_type, x, y, end_x, end_y, successful, is_goal, is_assist,
    is_progressive, is_penalty, shot_outcome, attacking_left_to_right,
    video_timestamp_ms, clip_url, recorded_at
FROM match_events
WHERE match_id = $1
  AND ($2::uuid IS NULL OR team_id = $2)
  AND ($3::uuid IS NULL OR player_id = $3)
  AND ($4::smallint IS NULL OR period = $4)
ORDER BY period, minute, second, video_timestamp_ms, event_id
"""


class StorageError(Exception):
    """Raised when a persistence operation fails."""


class PlayerProfilePersistenceError(StorageError):
    """Raised when a player-match profile cannot be upserted or loaded."""


class ConnectionPool(Protocol):
    """Minimal asyncpg pool surface used by :class:`DatabaseAggregator`."""

    def acquire(self) -> Any:
        """Return an async context manager yielding a connection."""

    async def close(self) -> None:
        """Release pool connections."""


def normalize_asyncpg_dsn(dsn: str) -> str:
    """Convert SQLAlchemy-style URLs into an asyncpg DSN.

    Args:
        dsn: Connection string, possibly using the ``postgresql+asyncpg://`` scheme.

    Returns:
        A DSN accepted by :func:`asyncpg.create_pool`.
    """

    stripped = dsn.strip()
    for prefix, replacement in (
        ("postgresql+asyncpg://", "postgresql://"),
        ("postgres+asyncpg://", "postgresql://"),
    ):
        if stripped.startswith(prefix):
            return replacement + stripped[len(prefix) :]
    return stripped


def split_sql_statements(sql: str) -> list[str]:
    """Split a DDL script into individual statements.

    Lines that are empty or comment-only are discarded. Statements must end
    with a semicolon.

    Args:
        sql: Contents of ``postgres_tables.sql``.

    Returns:
        Executable SQL statements without a trailing semicolon.
    """

    statements: list[str] = []
    buffer: list[str] = []
    for raw_line in sql.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(raw_line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            buffer = []
    leftover = "\n".join(buffer).strip().rstrip(";").strip()
    if leftover:
        statements.append(leftover)
    return statements


def _to_jsonb_payload(model: BaseModel) -> dict[str, Any]:
    """Dump a Pydantic sub-model to a JSON-ready dict without computed fields.

    Computed helpers such as ``success_rate`` are derived on read and must not
    be persisted, otherwise ``extra='forbid'`` would reject the document on
    reload.

    Args:
        model: Nested pillar model (defensive or distribution).

    Returns:
        A plain ``dict`` suitable for a JSONB bind parameter.
    """

    payload = model.model_dump(mode="json")
    return _drop_computed_fields(model, payload)


def _drop_computed_fields(model: BaseModel, payload: dict[str, Any]) -> dict[str, Any]:
    """Remove computed fields from ``payload`` recursively."""

    computed = set(getattr(type(model), "__pydantic_computed_fields__", {}) or {})
    for name in computed:
        payload.pop(name, None)
    for key, value in list(payload.items()):
        nested = getattr(model, key, None)
        if isinstance(nested, BaseModel) and isinstance(value, dict):
            payload[key] = _drop_computed_fields(nested, value)
    return payload


def _jsonb_param(payload: Mapping[str, Any]) -> str:
    """Encode a mapping as a JSON string for ``$n::jsonb`` bind parameters."""

    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _as_profile(profile: PlayerMatchProfile | PlayerMatchStats) -> PlayerMatchProfile:
    """Accept collector snapshots or persistence profiles."""

    return PlayerMatchProfile.from_stats(profile)


class DatabaseAggregator:
    """asyncpg connection pool and player-profile upsert service.

    Args:
        dsn: PostgreSQL DSN (``postgresql://`` or ``postgresql+asyncpg://``).
        min_size: Minimum pooled connections.
        max_size: Maximum pooled connections.
        command_timeout: Per-command timeout in seconds.
        pool: Optional pre-built pool (used by tests).
    """

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        command_timeout: float = 30.0,
        pool: ConnectionPool | None = None,
    ) -> None:
        if min_size < 1 or max_size < min_size:
            raise ValueError("Pool sizes must satisfy 1 <= min_size <= max_size.")
        self._dsn = normalize_asyncpg_dsn(dsn)
        self._min_size = min_size
        self._max_size = max_size
        self._command_timeout = command_timeout
        self._pool: ConnectionPool | None = pool

    @classmethod
    def from_env(
        cls,
        *,
        env_var: str = "DATABASE_URL",
        fallback: str | None = None,
    ) -> DatabaseAggregator:
        """Build an aggregator from ``DATABASE_URL`` or ``fallback``.

        Args:
            env_var: Environment variable holding the DSN.
            fallback: Optional DSN used when ``env_var`` is unset.

        Raises:
            StorageError: If neither the environment nor ``fallback`` supplies a DSN.
        """

        dsn = os.environ.get(env_var, fallback or "").strip()
        if not dsn:
            raise StorageError(f"Database DSN missing: set {env_var} or pass fallback.")
        return cls(dsn)

    async def connect(self) -> None:
        """Open the connection pool if one is not already attached."""

        if self._pool is not None:
            return
        try:
            self._pool = cast(
                ConnectionPool,
                await asyncpg.create_pool(
                    dsn=self._dsn,
                    min_size=self._min_size,
                    max_size=self._max_size,
                    command_timeout=self._command_timeout,
                ),
            )
        except (OSError, TimeoutError, asyncpg.PostgresError) as exc:
            LOGGER.exception("Failed to connect to PostgreSQL.")
            raise StorageError("Unable to open PostgreSQL connection pool.") from exc

    async def close(self) -> None:
        """Close the pool. Safe to call when already closed."""

        if self._pool is None:
            return
        try:
            await self._pool.close()
        except (OSError, asyncpg.PostgresError) as exc:
            LOGGER.exception("Failed to close PostgreSQL pool.")
            raise StorageError("Unable to close PostgreSQL connection pool.") from exc
        finally:
            self._pool = None

    async def __aenter__(self) -> DatabaseAggregator:
        await self.connect()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    def _require_pool(self) -> ConnectionPool:
        if self._pool is None:
            raise StorageError("DatabaseAggregator.connect() has not been called.")
        return self._pool

    async def apply_schema(self, schema_path: Path | None = None) -> None:
        """Execute ``postgres_tables.sql`` against the connected database.

        Args:
            schema_path: Optional override; defaults to the packaged DDL file.

        Raises:
            StorageError: If the script cannot be read or applied.
        """

        path = schema_path or SCHEMA_PATH
        try:
            sql = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Unable to read schema file: {path}") from exc
        try:
            pool = self._require_pool()
            async with pool.acquire() as connection:
                for statement in split_sql_statements(sql):
                    await connection.execute(statement)
        except StorageError:
            raise
        except (OSError, asyncpg.PostgresError) as exc:
            LOGGER.exception("Failed to apply PostgreSQL schema.")
            raise StorageError("Unable to apply postgres_tables.sql.") from exc

    async def ping(self) -> None:
        """Execute ``SELECT 1`` to confirm the pool is usable.

        Raises:
            StorageError: If the pool is closed or PostgreSQL does not answer.
        """

        try:
            pool = self._require_pool()
            async with pool.acquire() as connection:
                await connection.execute("SELECT 1")
        except StorageError:
            raise
        except (OSError, asyncpg.PostgresError) as exc:
            LOGGER.exception("PostgreSQL health check failed.")
            raise StorageError("PostgreSQL health check failed.") from exc

    async def upsert_player_profile(
        self,
        match_id: UUID,
        profile: PlayerMatchProfile | PlayerMatchStats,
    ) -> UUID:
        """Insert or update a player-match profile for a live match.

        Flattened offensive fields are written as typed columns. Nested
        :class:`~data_models.player_stats.DefensiveStats` and
        :class:`~data_models.player_stats.DistributionStats` are serialised to
        JSONB. A missing ``matches`` row is created as a live stub so the
        foreign key does not block in-play tagging.

        Args:
            match_id: Match the profile belongs to. Must equal ``profile.match_id``.
            profile: Validated three-pillar player-match document.

        Returns:
            The stable ``stats_id`` of the upserted row.

        Raises:
            ValueError: If ``match_id`` does not match the profile.
            PlayerProfilePersistenceError: If PostgreSQL rejects the write.
        """

        try:
            resolved = _as_profile(profile)
            if resolved.match_id != match_id:
                raise ValueError(
                    f"profile.match_id ({resolved.match_id}) does not match "
                    f"argument match_id ({match_id})."
                )
            arguments = _bind_profile_arguments(match_id, resolved)
            pool = self._require_pool()
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(ENSURE_MATCH_SQL, match_id)
                    stats_id = await connection.fetchval(
                        UPSERT_PLAYER_PROFILE_SQL,
                        *arguments,
                    )
            if not isinstance(stats_id, UUID):
                raise PlayerProfilePersistenceError("Upsert did not return a stats_id UUID.")
            return stats_id
        except PlayerProfilePersistenceError:
            raise
        except StorageError:
            raise
        except ValueError:
            raise
        except ValidationError as exc:
            LOGGER.exception("Player profile failed validation before upsert.")
            raise PlayerProfilePersistenceError(
                "PlayerMatchProfile is invalid and cannot be persisted."
            ) from exc
        except (OSError, TypeError, json.JSONDecodeError, asyncpg.PostgresError) as exc:
            LOGGER.exception(
                "Failed to upsert player profile player_id=%s match_id=%s",
                getattr(profile, "player_id", None),
                match_id,
            )
            raise PlayerProfilePersistenceError("Unable to upsert player_match_stats row.") from exc

    async def fetch_player_profile(
        self,
        player_id: UUID,
        match_id: UUID,
    ) -> PlayerMatchProfile | None:
        """Load a persisted profile, or ``None`` if the row does not exist.

        Args:
            player_id: Player to load.
            match_id: Match to load.
        """

        try:
            pool = self._require_pool()
            async with pool.acquire() as connection:
                row = await connection.fetchrow(FETCH_PLAYER_PROFILE_SQL, player_id, match_id)
        except StorageError:
            raise
        except (OSError, asyncpg.PostgresError, TypeError, ValueError) as exc:
            LOGGER.exception(
                "Failed to fetch player profile player_id=%s match_id=%s",
                player_id,
                match_id,
            )
            raise PlayerProfilePersistenceError("Unable to load player_match_stats row.") from exc
        if row is None:
            return None
        try:
            return _row_to_profile(row)
        except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.exception("Persisted player profile failed schema validation.")
            raise PlayerProfilePersistenceError(
                "Stored player_match_stats row is not a valid PlayerMatchProfile."
            ) from exc

    async def upsert_match_events(
        self,
        match_id: UUID,
        events: Sequence[MatchEvent],
    ) -> int:
        """Persist a batch of tagged events and their video-seek index rows.

        Designed for AutoData Advanced match feeds (1,000+ events). All writes
        run in one transaction after ensuring the parent ``matches`` row exists.

        Args:
            match_id: Parent match. Must equal every event's ``match_id``.
            events: Tagged events with video-sync anchors.

        Returns:
            Number of events upserted.

        Raises:
            ValueError: If an event belongs to a different match.
            PlayerProfilePersistenceError: If PostgreSQL rejects the write.
        """

        if not events:
            return 0
        for event in events:
            if event.match_id != match_id:
                raise ValueError(
                    f"event.match_id ({event.match_id}) does not match "
                    f"argument match_id ({match_id})."
                )
        try:
            pool = self._require_pool()
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(ENSURE_MATCH_SQL, match_id)
                    await connection.executemany(
                        UPSERT_MATCH_EVENT_SQL,
                        [_match_event_arguments(event) for event in events],
                    )
                    await connection.executemany(
                        UPSERT_VIDEO_CLIP_INDEX_SQL,
                        [_video_clip_arguments(event) for event in events],
                    )
            return len(events)
        except StorageError:
            raise
        except ValueError:
            raise
        except (OSError, TypeError, asyncpg.PostgresError) as exc:
            LOGGER.exception("Failed to upsert match events match_id=%s", match_id)
            raise PlayerProfilePersistenceError("Unable to upsert match_events rows.") from exc

    async def fetch_match_events(
        self,
        match_id: UUID,
        *,
        team_id: UUID | None = None,
        player_id: UUID | None = None,
        period: int | None = None,
    ) -> list[MatchEvent]:
        """Load tagged events for a match, optionally narrowed by team/player/half."""

        try:
            pool = self._require_pool()
            async with pool.acquire() as connection:
                rows = await connection.fetch(
                    FETCH_MATCH_EVENTS_SQL,
                    match_id,
                    team_id,
                    player_id,
                    period,
                )
        except StorageError:
            raise
        except (OSError, asyncpg.PostgresError, TypeError, ValueError) as exc:
            LOGGER.exception("Failed to fetch match events match_id=%s", match_id)
            raise PlayerProfilePersistenceError("Unable to load match_events rows.") from exc
        return [_row_to_match_event(row) for row in rows]


def _match_event_arguments(event: MatchEvent) -> tuple[object, ...]:
    """Bind parameters for :data:`UPSERT_MATCH_EVENT_SQL`."""

    return (
        event.event_id,
        event.match_id,
        event.team_id,
        event.player_id,
        event.period,
        event.minute,
        event.second,
        event.event_type.value,
        event.x,
        event.y,
        event.end_x,
        event.end_y,
        event.successful,
        event.is_goal,
        event.is_assist,
        event.is_progressive,
        event.is_penalty,
        None if event.shot_outcome is None else event.shot_outcome.value,
        event.attacking_left_to_right,
        resolve_video_timestamp_ms(event),
        resolve_clip_url(event),
        event.recorded_at,
    )


def _video_clip_arguments(event: MatchEvent) -> tuple[object, ...]:
    """Bind parameters for :data:`UPSERT_VIDEO_CLIP_INDEX_SQL`."""

    anchor = video_anchor_from_event(event)
    return (
        event.event_id,
        event.match_id,
        event.team_id,
        event.player_id,
        event.event_type.value,
        highlight_kind(event),
        anchor.video_timestamp_ms,
        anchor.clip_url,
        anchor.duration_ms,
    )


def _row_to_match_event(row: Mapping[str, Any]) -> MatchEvent:
    """Rehydrate a ``match_events`` row."""

    return MatchEvent.model_validate(
        {
            "event_id": row["event_id"],
            "match_id": row["match_id"],
            "team_id": row["team_id"],
            "player_id": row["player_id"],
            "period": int(row["period"]),
            "minute": int(row["minute"]),
            "second": int(row["second"]),
            "event_type": row["event_type"],
            "x": float(row["x"]),
            "y": float(row["y"]),
            "end_x": None if row["end_x"] is None else float(row["end_x"]),
            "end_y": None if row["end_y"] is None else float(row["end_y"]),
            "successful": bool(row["successful"]),
            "is_goal": bool(row["is_goal"]),
            "is_assist": bool(row["is_assist"]),
            "is_progressive": bool(row["is_progressive"]),
            "is_penalty": bool(row["is_penalty"]),
            "shot_outcome": row["shot_outcome"],
            "attacking_left_to_right": bool(row["attacking_left_to_right"]),
            "video_timestamp_ms": int(row["video_timestamp_ms"]),
            "clip_url": str(row["clip_url"] or ""),
            "recorded_at": row["recorded_at"],
        }
    )


def _bind_profile_arguments(
    match_id: UUID,
    profile: PlayerMatchProfile,
) -> tuple[object, ...]:
    """Map a profile onto the upsert bind parameters."""

    offensive: OffensiveStats = profile.offensive
    defensive_payload = _to_jsonb_payload(profile.defensive)
    distribution_payload = _to_jsonb_payload(profile.distribution)
    possession_payload = _to_jsonb_payload(profile.possession)
    return (
        profile.player_id,
        match_id,
        profile.stats_id,
        profile.team_id,
        profile.jersey_number,
        profile.player_name,
        profile.position,
        offensive.minutes,
        offensive.goals,
        offensive.assists,
        offensive.total_shots,
        offensive.shots_on_target,
        offensive.blocked_shots,
        offensive.missed_shots,
        offensive.shots_inside_penalty_area,
        offensive.shots_outside_penalty_area,
        offensive.offsides,
        offensive.freekicks,
        offensive.corners,
        offensive.penalty_kicks,
        offensive.throw_ins,
        _jsonb_param(defensive_payload),
        _jsonb_param(distribution_payload),
        _jsonb_param(possession_payload),
        profile.collected_at,
    )


def _decode_jsonb(value: object) -> dict[str, Any]:
    """Accept a dict (codec-decoded) or a JSON string from asyncpg."""

    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if not isinstance(loaded, dict):
            raise ValueError("JSONB payload must be an object.")
        return loaded
    raise TypeError(f"Unsupported JSONB payload type: {type(value)!r}")


def _row_to_profile(row: Mapping[str, Any]) -> PlayerMatchProfile:
    """Rehydrate a database row into :class:`PlayerMatchProfile`."""

    minutes = row["minutes"]
    offensive = OffensiveStats(
        minutes=float(minutes),
        goals=int(row["goals"]),
        assists=int(row["assists"]),
        total_shots=int(row["total_shots"]),
        shots_on_target=int(row["shots_on_target"]),
        blocked_shots=int(row["blocked_shots"]),
        missed_shots=int(row["missed_shots"]),
        shots_inside_penalty_area=int(row["shots_inside_penalty_area"]),
        shots_outside_penalty_area=int(row["shots_outside_penalty_area"]),
        offsides=int(row["offsides"]),
        freekicks=int(row["freekicks"]),
        corners=int(row["corners"]),
        penalty_kicks=int(row.get("penalty_kicks") or 0),
        throw_ins=int(row.get("throw_ins") or 0),
    )
    possession_raw = row.get("possession") or {}
    return PlayerMatchProfile(
        stats_id=row["stats_id"],
        match_id=row["match_id"],
        player_id=row["player_id"],
        team_id=row["team_id"],
        jersey_number=row["jersey_number"],
        player_name=str(row.get("player_name") or ""),
        position=row["position"],
        offensive=offensive,
        defensive=DefensiveStats.model_validate(_decode_jsonb(row["defensive"])),
        distribution=DistributionStats.model_validate(_decode_jsonb(row["distribution"])),
        possession=PossessionStats.model_validate(
            _decode_jsonb(possession_raw) if possession_raw else {}
        ),
        collected_at=row["collected_at"],
    )


@asynccontextmanager
async def connected_aggregator(dsn: str) -> AsyncIterator[DatabaseAggregator]:
    """Yield a connected aggregator and close it afterwards.

    Args:
        dsn: PostgreSQL DSN.
    """

    aggregator = DatabaseAggregator(dsn)
    try:
        await aggregator.connect()
        yield aggregator
    finally:
        await aggregator.close()
