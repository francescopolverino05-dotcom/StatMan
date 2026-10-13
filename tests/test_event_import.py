"""Tests for StatsBomb / Opta event-data import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from statman import event_import


@pytest.fixture
def statsbomb_events_path() -> Path:
    path = Path("/tmp/sb_8657_events.json")
    if not path.exists():
        pytest.skip("StatsBomb sample events not downloaded")
    return path


@pytest.fixture
def statsbomb_lineups_path() -> Path:
    path = Path("/tmp/sb_8657_lineups.json")
    if not path.exists():
        pytest.skip("StatsBomb sample lineups not downloaded")
    return path


@pytest.fixture
def statsbomb_match_path() -> Path:
    path = Path("/tmp/sb_matches_43_3.json")
    if not path.exists():
        pytest.skip("StatsBomb sample matches not downloaded")
    return path


def test_detect_statsbomb_format(statsbomb_events_path: Path):
    payload = json.loads(statsbomb_events_path.read_text())
    assert event_import.detect_format(payload, "8657.json") == "statsbomb"


def test_import_statsbomb_full_match(
    statsbomb_events_path: Path,
    statsbomb_lineups_path: Path,
    statsbomb_match_path: Path,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(event_import, "ROOT", tmp_path / "imports")
    with statsbomb_events_path.open("rb") as ev, statsbomb_lineups_path.open(
        "rb"
    ) as lu, statsbomb_match_path.open("rb") as mt:
        result = event_import.import_statsbomb(
            ev,
            "8657.json",
            lineups_file=lu,
            lineups_filename="8657_lineups.json",
            match_file=mt,
            match_filename="matches.json",
            game_id=8657,
            home_team_id=782,
        )
    assert result["format"] == "statsbomb"
    assert result["import_id"]
    stats = result["stats"]
    assert stats["match"]["game_id"] == 8657
    assert stats["match"]["home_team"] == "Belgium"
    assert stats["match"]["away_team"] == "England"
    assert len(stats["teams"]) == 2
    # Provider-grade fields should be present (not None for both teams' pass volume).
    assert sum(t["passes_attempted"] for t in stats["teams"]) > 100
    assert sum(t["xg"] or 0 for t in stats["teams"]) > 0
    stored = event_import.get_import(result["import_id"])
    assert stored is not None
    assert stored["match"]["home_score"] == 2


def test_import_statsbomb_events_only_infers_lineups(
    statsbomb_events_path: Path,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(event_import, "ROOT", tmp_path / "imports")
    with statsbomb_events_path.open("rb") as ev:
        result = event_import.import_events_auto(ev, "8657.json", game_id=8657, home_team_id=782)
    assert result["format"] == "statsbomb"
    assert len(result["stats"]["teams"]) == 2
