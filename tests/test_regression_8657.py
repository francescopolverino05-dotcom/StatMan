"""Locked regression fixture for Belgium–England WC2018 (game 8657).

Pinning the StatsBomb sheet catalog so definition/count drift fails CI.
Requires network on first StatsBomb open-data fetch (cached thereafter).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from statman.compute import CATALOG_VERSION, compute_match_stats
from statman.load import load_match

FIXTURE = Path(__file__).parent / "fixtures" / "belgium_england_8657_catalog.json"


@pytest.fixture(scope="module")
def live_stats():
    try:
        return compute_match_stats(load_match(8657))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Could not load StatsBomb open match 8657: {exc}")


def test_catalog_version_locked(live_stats):
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert live_stats["catalog_version"] == CATALOG_VERSION
    assert live_stats["catalog_version"] == expected["catalog_version"]
    assert live_stats["source"].get("catalog_locked") is True


def test_belgium_england_team_catalog_regression(live_stats):
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert live_stats["match"]["game_id"] == 8657

    by_name = {t["team_name"]: t for t in live_stats["teams"]}
    assert set(by_name) == set(expected["teams"])

    for team_name, exp in expected["teams"].items():
        got = by_name[team_name]
        for key, value in exp.items():
            assert got.get(key) == value, f"{team_name}.{key}: got {got.get(key)!r} != {value!r}"
        # Tackles must surface on the defence board section.
        assert got["sections"]["defence"]["tackles"] == exp["tackles"]


def test_belgium_england_goalkeeper_regression(live_stats):
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    keepers = [
        {
            "player_name": p["player_name"],
            "team_name": p["team_name"],
            "shots_faced": p["shots_faced"],
            "saves": p["saves"],
            "goals_conceded": p["goals_conceded"],
            "save_pct": p["save_pct"],
        }
        for p in live_stats["players"]
        if p.get("is_goalkeeper")
    ]
    keepers = sorted(keepers, key=lambda r: r["team_name"])
    assert keepers == expected["goalkeepers"]
