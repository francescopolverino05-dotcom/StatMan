"""Football Analytics AutoData API.

Local run::

    uvicorn api.main:app --host 0.0.0.0 --port 8000

or ``python -m api.main`` / the ``enjoystats`` console script.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final, Protocol
from uuid import UUID

import asyncpg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from data_models.player_stats import PlayerMatchProfile, PlayerMatchStats
from storage.db_aggregator import (
    DatabaseAggregator,
    PlayerProfilePersistenceError,
    StorageError,
)

LOGGER = logging.getLogger("enjoystats.api")

API_TITLE: Final[str] = "Football Analytics AutoData API"
API_VERSION: Final[str] = "0.1.0"
DEFAULT_DATABASE_URL: Final[str] = "postgresql://enjoystats:enjoystats@localhost:5432/enjoystats"


class APISettings(BaseSettings):
    """Process settings for Uvicorn and the PostgreSQL aggregator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        validation_alias=AliasChoices("DATABASE_URL", "ENJOYSTATS_DATABASE_URL"),
    )
    host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("ENJOYSTATS_HOST", "HOST"),
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("ENJOYSTATS_PORT", "PORT"),
    )
    debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("ENJOYSTATS_DEBUG", "DEBUG"),
    )


class PlayerProfileStore(Protocol):
    """Persistence surface required by the HTTP routes."""

    async def upsert_player_profile(
        self,
        match_id: UUID,
        profile: PlayerMatchProfile | PlayerMatchStats,
    ) -> UUID:
        """Insert or update a player-match profile."""

    async def fetch_player_profile(
        self,
        player_id: UUID,
        match_id: UUID,
    ) -> PlayerMatchProfile | None:
        """Load a profile, or ``None`` when the row does not exist."""


def load_settings() -> APISettings:
    """Load API settings from the environment and optional ``.env`` file."""

    return APISettings()


def _error_body(*, error: str, message: str, status_code: int) -> dict[str, Any]:
    """Return the standardized JSON error envelope."""

    return {"error": error, "message": message, "status": status_code}


def _json_safe(value: Any) -> Any:
    """Coerce nested exception objects into JSON-serializable values."""

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _http_exception_message(detail: object) -> str:
    """Flatten FastAPI/Starlette ``detail`` into a client-safe string."""

    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "Request failed."
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return "Request failed."


def create_app(
    *,
    aggregator: PlayerProfileStore | None = None,
    settings: APISettings | None = None,
) -> FastAPI:
    """Build the FastAPI application.

    Args:
        aggregator: Optional pre-built store. When omitted, a
            :class:`~storage.db_aggregator.DatabaseAggregator` is opened
            from ``DATABASE_URL`` during the app lifespan.
        settings: Optional process settings. Loaded from the environment
            when omitted.

    Returns:
        A fully configured FastAPI application.
    """

    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open and close the asyncpg aggregator with the application."""

        injected = aggregator is not None
        store: PlayerProfileStore
        if aggregator is not None:
            store = aggregator
        else:
            engine = DatabaseAggregator(resolved_settings.database_url)
            try:
                await engine.connect()
                await engine.apply_schema()
            except StorageError:
                LOGGER.exception("PostgreSQL aggregator failed to start.")
                raise
            store = engine
        app.state.aggregator = store
        app.state.settings = resolved_settings
        try:
            yield
        finally:
            if not injected and isinstance(store, DatabaseAggregator):
                await store.close()
            app.state.aggregator = None

    application = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        description=(
            "Real-time football event tagging and player-match statistics. "
            "Offensive metrics are flattened; defensive and distribution "
            "pillars are nested success/total documents."
        ),
        lifespan=lifespan,
    )
    _register_exception_handlers(application)
    _register_routes(application)
    from api.routes import advanced_router

    application.include_router(advanced_router)
    return application


async def get_aggregator(request: Request) -> PlayerProfileStore:
    """Resolve the process-wide :class:`DatabaseAggregator` (or test double).

    Raises:
        StorageError: If the lifespan hook has not attached a store.
    """

    store = getattr(request.app.state, "aggregator", None)
    if store is None:
        raise StorageError("Database aggregator is not initialized.")
    return store


def _register_exception_handlers(application: FastAPI) -> None:
    """Install global JSON handlers for persistence and validation failures."""

    @application.exception_handler(PlayerProfilePersistenceError)
    async def persistence_error_handler(
        _request: Request,
        exc: PlayerProfilePersistenceError,
    ) -> JSONResponse:
        LOGGER.exception("Player profile persistence failed.")
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content=_error_body(
                error="database_operation_failed",
                message=str(exc) or "Unable to read or write player match stats.",
                status_code=status_code,
            ),
        )

    @application.exception_handler(StorageError)
    async def storage_error_handler(
        _request: Request,
        exc: StorageError,
    ) -> JSONResponse:
        LOGGER.exception("Database storage layer failed.")
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content=_error_body(
                error="database_unavailable",
                message=str(exc) or "Unable to reach the football stats database.",
                status_code=status_code,
            ),
        )

    @application.exception_handler(asyncpg.PostgresError)
    async def postgres_error_handler(
        _request: Request,
        exc: asyncpg.PostgresError,
    ) -> JSONResponse:
        LOGGER.exception("Unhandled PostgreSQL error in API request.")
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content=_error_body(
                error="database_unavailable",
                message="Database connection failed while processing the request.",
                status_code=status_code,
            ),
        )

    @application.exception_handler(OSError)
    async def os_error_handler(_request: Request, exc: OSError) -> JSONResponse:
        LOGGER.exception("OS-level database connection failure.")
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(
            status_code=status_code,
            content=_error_body(
                error="database_unavailable",
                message="Database connection failed while processing the request.",
                status_code=status_code,
            ),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        status_code = 422
        return JSONResponse(
            status_code=status_code,
            content={
                "error": "validation_error",
                "message": "Request payload failed PlayerMatchProfile validation.",
                "status": status_code,
                "details": _json_safe(exc.errors()),
            },
        )

    @application.exception_handler(HTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(
                error="http_error",
                message=_http_exception_message(exc.detail),
                status_code=exc.status_code,
            ),
            headers=dict(exc.headers) if exc.headers else None,
        )


def _register_routes(application: FastAPI) -> None:
    """Register versioned player-profile endpoints."""

    @application.get(
        "/health",
        summary="Liveness and database readiness",
        responses={503: {"description": "Database aggregator is unavailable."}},
    )
    async def health(store: PlayerProfileStore = Depends(get_aggregator)) -> dict[str, str]:
        """Return ``ok`` once the aggregator can answer a trivial query."""

        ping = getattr(store, "ping", None)
        if callable(ping):
            result = ping()
            if hasattr(result, "__await__"):
                await result
        return {"status": "ok", "service": "api"}

    @application.get(
        "/api/v1/matches/{match_id}/players/{player_id}",
        response_model=PlayerMatchProfile,
        summary="Get a player-match profile",
        responses={
            404: {"description": "Profile not found for this match and player."},
            503: {"description": "Database unavailable."},
        },
    )
    async def get_player_match_profile(
        match_id: UUID,
        player_id: UUID,
        store: PlayerProfileStore = Depends(get_aggregator),
    ) -> PlayerMatchProfile:
        """Return the stored offensive, defensive, and distribution pillars."""

        profile = await store.fetch_player_profile(player_id, match_id)
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Player profile not found for this match.",
            )
        return profile

    @application.post(
        "/api/v1/matches/{match_id}/players",
        response_model=PlayerMatchProfile,
        summary="Upsert a live player-match profile",
        responses={
            400: {"description": "Path match_id does not match the payload."},
            422: {"description": "Payload failed PlayerMatchProfile validation."},
            503: {"description": "Database unavailable."},
        },
    )
    async def upsert_player_match_profile(
        match_id: UUID,
        profile: PlayerMatchProfile,
        store: PlayerProfileStore = Depends(get_aggregator),
    ) -> PlayerMatchProfile:
        """Validate JSON as :class:`PlayerMatchProfile` and persist it.

        The path ``match_id`` is authoritative. A body whose ``match_id``
        differs is rejected rather than silently rewritten.
        """

        if profile.match_id != match_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("JSON match_id does not match the match_id in the URL path."),
            )
        await store.upsert_player_profile(match_id, profile)
        persisted = await store.fetch_player_profile(profile.player_id, match_id)
        if persisted is None:
            raise PlayerProfilePersistenceError(
                "Upsert succeeded but the player profile could not be reloaded."
            )
        return persisted


app = create_app()


def run() -> None:
    """Start Uvicorn with host/port from the environment."""

    settings = load_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )


def main() -> None:
    """Module entry point used by ``python -m api.main``."""

    run()


if __name__ == "__main__":
    main()
