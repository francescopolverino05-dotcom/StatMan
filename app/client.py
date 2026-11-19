"""Async FastAPI client for the EnjoyStats dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import httpx

from app.dummy_data import (
    PitchAction,
    fallback_actions,
    fallback_directions,
    fallback_profile,
    match_actions,
)
from app.metrics import PassDirections, directions_from_distribution
from data_models.player_stats import PlayerMatchProfile

DEFAULT_BASE_URL = os.environ.get("ENJOYSTATS_API_URL", "http://127.0.0.1:8000")
REQUEST_TIMEOUT_S = 3.0


@dataclass(frozen=True, slots=True)
class ProfileLoad:
    """A player-match profile plus whether it came from live API or fallback."""

    profile: PlayerMatchProfile
    directions: PassDirections
    source: Literal["live", "fallback"]
    message: str
    api_online: bool
    actions: tuple[PitchAction, ...] = ()


def _without_computed_fields(value: Any, *, parent_key: str | None = None) -> Any:
    """Drop GET-only computed keys so StrictModel can re-validate the payload."""

    computed = {"shot_accuracy", "failed", "success_rate"}
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in computed:
                continue
            if key == "total" and parent_key in {"blocks", "ball_recoveries", "ball_lost"}:
                continue
            cleaned[key] = _without_computed_fields(item, parent_key=key)
        return cleaned
    if isinstance(value, list):
        return [_without_computed_fields(item, parent_key=parent_key) for item in value]
    return value


def _fallback(match_id: UUID, player_id: UUID, *, api_online: bool, reason: str) -> ProfileLoad:
    profile = fallback_profile(match_id, player_id)
    return ProfileLoad(
        profile=profile,
        directions=fallback_directions(match_id, player_id),
        source="fallback",
        message=reason,
        api_online=api_online,
        actions=fallback_actions(match_id, player_id),
    )


async def probe_api(base_url: str, *, timeout_s: float = REQUEST_TIMEOUT_S) -> bool:
    """Return whether the FastAPI process answers OpenAPI."""

    url = f"{base_url.rstrip('/')}/openapi.json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout_s)
    except httpx.RequestError:
        return False
    return response.status_code == 200


async def fetch_player_profile(
    base_url: str,
    match_id: UUID,
    player_id: UUID,
    *,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> ProfileLoad:
    """GET a profile from FastAPI, falling back to dummy data on any failure.

    Args:
        base_url: API origin, e.g. ``http://127.0.0.1:8000``.
        match_id: Match UUID from the sidebar.
        player_id: Player UUID from the sidebar.
        timeout_s: Per-request timeout.
    """

    online = await probe_api(base_url, timeout_s=timeout_s)
    if not online:
        return _fallback(
            match_id,
            player_id,
            api_online=False,
            reason="FastAPI is unreachable — showing simulated dummy values.",
        )

    url = f"{base_url.rstrip('/')}/api/v1/matches/{match_id}/players/{player_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout_s)
    except httpx.RequestError:
        return _fallback(
            match_id,
            player_id,
            api_online=False,
            reason="FastAPI connection dropped during GET — showing dummy values.",
        )

    if response.status_code == 404:
        return _fallback(
            match_id,
            player_id,
            api_online=True,
            reason="No live profile for this selection — showing dummy preview values.",
        )
    if response.status_code >= 400:
        return _fallback(
            match_id,
            player_id,
            api_online=True,
            reason=f"API returned HTTP {response.status_code} — showing dummy values.",
        )
    try:
        profile = PlayerMatchProfile.model_validate(_without_computed_fields(response.json()))
    except (ValueError, TypeError) as exc:
        return _fallback(
            match_id,
            player_id,
            api_online=True,
            reason=f"Live payload failed validation ({exc}) — showing dummy values.",
        )
    return ProfileLoad(
        profile=profile,
        directions=directions_from_distribution(profile.distribution),
        source="live",
        message="Live profile loaded from FastAPI.",
        api_online=True,
        actions=match_actions(match_id, player_id, include_generic=False),
    )
