"""Phase 3: possession merge + film-event team splits."""

from __future__ import annotations

import pytest

from statman.match_pack import store
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.phase3 import merge_tracking_into_sheet
from statman.match_pack.pipeline import create_pack, put_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.match_pack.tracking import assign_events_to_teams


@pytest.fixture()
def pack_root(tmp_path, monkeypatch):
    root = tmp_path / "match_packs"
    monkeypatch.setattr(store, "ROOT", root)
    store.ensure_root()
    return root


def test_assign_events_to_teams_by_timeline():
    timeline = [
        {"time_sec": 10.0, "team": "home"},
        {"time_sec": 20.0, "team": "away"},
        {"time_sec": 30.0, "team": "home"},
    ]
    events = [
        {"label": "Shot", "time_sec": 10.2},
        {"label": "Pass", "time_sec": 19.5},
        {"label": "Goal", "time_sec": 29.0},
        {"label": "Cross", "time_sec": 100.0},  # far from samples → unknown
    ]
    splits = assign_events_to_teams(events, timeline)
    assert splits["home"]["shots"] == 2  # Shot + Goal
    assert splits["away"]["passes"] == 1
    assert splits["events_tagged"] == 3
    assert splits["unknown"]["crosses"] == 1 or splits["unknown"]["labels"].get("Cross") == 1


def test_merge_tracking_fills_possession_and_shots(pack_root):
    meta = create_pack(home_team="Home", away_team="Away")
    put_facts(meta["pack_id"], EXAMPLE_FACTS)
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id=meta["pack_id"])
    tracking = {
        "method": "test",
        "possession": {
            "home_pct": 58.0,
            "away_pct": 42.0,
            "home_frames": 58,
            "away_frames": 42,
            "unknown_frames": 5,
            "known_frames": 100,
        },
        "cluster_to_side": {"0": "home", "1": "away"},
        "mapping_source": "anchored_goals",
        "samples": 100,
        "warning": "test",
    }
    splits = {
        "home": {"shots": 7, "passes": 40, "tackles": 1},
        "away": {"shots": 4, "passes": 35, "tackles": 0},
        "events_tagged": 80,
        "events_total": 100,
    }
    merged = merge_tracking_into_sheet(sheet, tracking, splits)
    home, away = merged["teams"]
    assert home["possession_pct"] == 58.0
    assert away["possession_pct"] == 42.0
    assert home["shots"] == 7
    assert away["shots"] == 4
    assert home["passes_attempted"] == 40
    assert merged["source"]["phase"] == "match-pack-phase3"
    assert merged["tracking"]["possession"]["home_pct"] == 58.0
    # Facts score untouched
    assert merged["match"]["home_score"] == 2
