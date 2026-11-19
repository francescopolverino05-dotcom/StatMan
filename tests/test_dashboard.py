"""Tests for dashboard dummy fallback, pass directions, and FastAPI client."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from app.client import fetch_player_profile
from app.dummy_data import (
    PLAYMAKER_ID,
    SHOWCASE_MATCH_ID,
    SIM_MATCH_ID,
    STRIKER_ID,
    catalog,
    fallback_actions,
    fallback_profile,
)
from app.metrics import PassDirections, directions_from_distribution
from data_models.player_stats import (
    AttemptSplit,
    DistributionStats,
    PassDirectionStats,
    PassLocationStats,
)


def test_catalog_covers_demo_and_showcase_players() -> None:
    rows = catalog()
    assert {row["player_id"] for row in rows} >= {PLAYMAKER_ID, STRIKER_ID}
    assert any(row["match_id"] == SIM_MATCH_ID for row in rows)
    assert any(row["match_id"] == SHOWCASE_MATCH_ID for row in rows)


def test_dummy_playmaker_and_striker_match_pipeline_story() -> None:
    playmaker = fallback_profile(SIM_MATCH_ID, PLAYMAKER_ID)
    striker = fallback_profile(SIM_MATCH_ID, STRIKER_ID)
    assert playmaker.distribution.passes.success_rate == 1.0
    assert playmaker.distribution.passes.total == 3
    assert striker.offensive.goals == 1
    assert striker.offensive.shots_on_target == 1
    assert striker.offensive.shots_inside_penalty_area == 1
    assert striker.defensive.ground_duels.success_rate == 1.0


def test_unknown_ids_still_return_a_valid_profile() -> None:
    profile = fallback_profile(uuid4(), uuid4())
    assert profile.offensive.goals >= 0
    assert profile.distribution.passes.total >= profile.distribution.passes.success


def test_direction_split_uses_explicit_or_derives_from_distribution() -> None:
    explicit = PassDirections(forward=10, sideways=4, backward=2)
    empty = DistributionStats()
    assert directions_from_distribution(empty, explicit=explicit) == explicit
    derived = directions_from_distribution(
        DistributionStats(
            passes=AttemptSplit(success=8, total=10),
            progressive_passes=AttemptSplit(success=3, total=4),
            cutbacks=AttemptSplit(success=1, total=2),
            pass_locations=PassLocationStats(
                short=AttemptSplit(success=4, total=5),
                medium=AttemptSplit(success=3, total=4),
                long=AttemptSplit(success=1, total=1),
            ),
            pass_directions=PassDirectionStats(
                forward=AttemptSplit(success=5, total=6),
                sideways=AttemptSplit(success=2, total=3),
                backward=AttemptSplit(success=1, total=1),
            ),
        )
    )
    assert derived.forward == 6
    assert derived.sideways == 3
    assert derived.backward == 1
    assert derived.as_rows()[0]["Direction"] == "Forward"


@pytest.mark.asyncio
async def test_fetch_falls_back_when_api_is_offline() -> None:
    with patch("app.client.probe_api", new=AsyncMock(return_value=False)):
        load = await fetch_player_profile("http://127.0.0.1:9", SIM_MATCH_ID, PLAYMAKER_ID)
    assert load.source == "fallback"
    assert load.api_online is False
    assert load.profile.player_id == PLAYMAKER_ID
    assert "unreachable" in load.message.lower()
    assert len(load.actions) == 3
    assert all(action.event_type == "pass" for action in load.actions)


@pytest.mark.asyncio
async def test_fetch_uses_live_payload_when_api_returns_profile() -> None:
    live = fallback_profile(SIM_MATCH_ID, STRIKER_ID)
    payload = live.model_dump(mode="json", exclude_computed_fields=True)
    response = httpx.Response(200, json=payload)
    with (
        patch("app.client.probe_api", new=AsyncMock(return_value=True)),
        patch("httpx.AsyncClient.get", new=AsyncMock(return_value=response)),
    ):
        load = await fetch_player_profile("http://127.0.0.1:8000", SIM_MATCH_ID, STRIKER_ID)
    assert load.source == "live"
    assert load.profile.offensive.goals == 1
    assert load.api_online is True
    assert len(load.actions) == 1
    assert load.actions[0].is_goal is True


def test_dashboard_renders_fallback_without_network() -> None:
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[1] / "app" / "dashboard.py"
    at = AppTest.from_file(str(script), default_timeout=15)
    at.run()
    assert not at.exception
    titles = [str(element.value) for element in at.title]
    assert any("EnjoyStats" in title for title in titles)
    subheaders = [str(element.value) for element in at.subheader]
    assert "Offensive" in subheaders
    assert "Defensive" in subheaders
    assert "Distribution" in subheaders
    assert "Possession" in subheaders
    assert "Tactical pitch" in subheaders


def test_unknown_fallback_actions_include_a_missing_coordinate() -> None:
    actions = fallback_actions(uuid4(), uuid4())
    assert any(action.x is None or action.y is None for action in actions)
    assert any(action.event_type == "shot" and action.is_goal for action in actions)
