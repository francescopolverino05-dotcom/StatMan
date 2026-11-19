"""HTTP tests for the Football Analytics AutoData API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import API_TITLE, create_app, get_aggregator
from data_models.player_stats import (
    AttemptSplit,
    DefensiveStats,
    DistributionStats,
    OffensiveStats,
    PassLocationStats,
    PlayerMatchProfile,
)
from storage.db_aggregator import PlayerProfilePersistenceError, StorageError
from tests.fakes import InMemoryProfileStore


def _sample_profile(**overrides: object) -> PlayerMatchProfile:
    payload: dict[str, object] = {
        "match_id": overrides.get("match_id", uuid4()),
        "player_id": overrides.get("player_id", uuid4()),
        "team_id": overrides.get("team_id", uuid4()),
        "jersey_number": 9,
        "position": "ST",
        "offensive": OffensiveStats(
            minutes=12.5,
            goals=1,
            assists=0,
            total_shots=2,
            shots_on_target=1,
            blocked_shots=0,
            missed_shots=1,
            shots_inside_penalty_area=2,
            shots_outside_penalty_area=0,
        ),
        "defensive": DefensiveStats(
            aerial_duels=AttemptSplit(success=1, total=2),
        ),
        "distribution": DistributionStats(
            passes=AttemptSplit(success=8, total=10),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=5, total=6),
                medium=AttemptSplit(success=2, total=3),
                long=AttemptSplit(success=1, total=1),
            ),
        ),
        "collected_at": datetime(2026, 9, 18, 15, 20, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return PlayerMatchProfile.model_validate(payload)


def _json_payload(profile: PlayerMatchProfile) -> dict[str, Any]:
    return profile.model_dump(mode="json", exclude_computed_fields=True)


class _FailingStore(InMemoryProfileStore):
    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self._exc = exc

    async def fetch_player_profile(
        self,
        player_id: UUID,
        match_id: UUID,
    ) -> PlayerMatchProfile | None:
        raise self._exc

    async def upsert_player_profile(
        self,
        match_id: UUID,
        profile: PlayerMatchProfile,
    ) -> UUID:
        raise self._exc


@pytest.fixture
def store() -> InMemoryProfileStore:
    return InMemoryProfileStore()


@pytest.fixture
def client(store: InMemoryProfileStore) -> Any:
    application = create_app(aggregator=store)
    with TestClient(application) as test_client:
        yield test_client


def test_openapi_title(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == API_TITLE


def test_health_ok_when_aggregator_is_injected(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


def test_get_player_profile(client: TestClient, store: InMemoryProfileStore) -> None:
    profile = _sample_profile()
    store.rows[(profile.player_id, profile.match_id)] = profile
    response = client.get(f"/api/v1/matches/{profile.match_id}/players/{profile.player_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["player_id"] == str(profile.player_id)
    assert body["offensive"]["goals"] == 1
    assert body["offensive"]["shots_on_target"] == 1
    assert body["defensive"]["aerial_duels"]["success"] == 1
    assert body["defensive"]["aerial_duels"]["total"] == 2
    assert body["distribution"]["passes"]["success"] == 8


def test_get_player_profile_not_found(client: TestClient) -> None:
    response = client.get(f"/api/v1/matches/{uuid4()}/players/{uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "http_error"
    assert body["status"] == 404
    assert "not found" in body["message"].lower()


def test_post_upserts_player_profile(client: TestClient, store: InMemoryProfileStore) -> None:
    profile = _sample_profile()
    response = client.post(
        f"/api/v1/matches/{profile.match_id}/players",
        json=_json_payload(profile),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stats_id"] == str(profile.stats_id)
    assert body["offensive"]["goals"] == 1
    assert body["distribution"]["passes"]["total"] == 10
    assert (profile.player_id, profile.match_id) in store.rows


def test_post_rejects_invalid_offensive_identity(client: TestClient) -> None:
    profile = _sample_profile()
    payload = _json_payload(profile)
    payload["offensive"]["total_shots"] = 99
    response = client.post(
        f"/api/v1/matches/{profile.match_id}/players",
        json=payload,
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "validation_error"
    assert body["status"] == 422
    assert "details" in body


def test_post_rejects_mismatched_match_id(client: TestClient) -> None:
    profile = _sample_profile()
    response = client.post(
        f"/api/v1/matches/{uuid4()}/players",
        json=_json_payload(profile),
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "http_error"
    assert "match_id" in body["message"]


def test_get_returns_standardized_database_unavailable_error() -> None:
    application = create_app(
        aggregator=_FailingStore(StorageError("Unable to open PostgreSQL connection pool."))
    )
    with TestClient(application) as client:
        response = client.get(f"/api/v1/matches/{uuid4()}/players/{uuid4()}")
    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "database_unavailable"
    assert body["status"] == 503
    assert "postgresql" in body["message"].lower()


def test_post_returns_standardized_persistence_error() -> None:
    profile = _sample_profile()
    application = create_app(
        aggregator=_FailingStore(
            PlayerProfilePersistenceError("Unable to upsert player_match_stats row.")
        )
    )
    with TestClient(application) as client:
        response = client.post(
            f"/api/v1/matches/{profile.match_id}/players",
            json=_json_payload(profile),
        )
    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "database_operation_failed"
    assert body["status"] == 503


def test_uninitialized_aggregator_is_database_unavailable() -> None:
    application = create_app(aggregator=InMemoryProfileStore())

    async def missing_store() -> Any:
        raise StorageError("Database aggregator is not initialized.")

    application.dependency_overrides[get_aggregator] = missing_store
    with TestClient(application) as client:
        response = client.get(f"/api/v1/matches/{uuid4()}/players/{uuid4()}")
    assert response.status_code == 503
    assert response.json()["error"] == "database_unavailable"
