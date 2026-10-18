"""Phase 10: remnant catalog fills from film + shots."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.remnants import (
    build_remnants,
    estimate_crosses,
    estimate_recoveries,
    estimate_shot_splits,
    merge_remnants_into_sheet,
)
from statman.match_pack.sheet_from_facts import sheet_from_facts


def test_recoveries_from_possession_flips():
    timeline = [
        {"time_sec": 0.0, "team": "home"},
        {"time_sec": 10.0, "team": "home"},
        {"time_sec": 12.0, "team": "away"},
        {"time_sec": 20.0, "team": "away"},
        {"time_sec": 22.0, "team": "home"},
    ]
    film = [
        {"time_sec": 12.0, "label": "Drive", "ball_xy": [640.0, 40.0]},
        {"time_sec": 22.0, "label": "Drive", "ball_xy": [640.0, 680.0]},
    ]
    out = estimate_recoveries(film, timeline, frame_h=720.0)
    assert out["away"]["recoveries"] == 1
    assert out["home"]["recoveries"] == 1
    assert out["home"]["balls_lost"] == 1
    assert out["away"]["balls_lost"] == 1


def test_crosses_completion_hold():
    timeline = [
        {"time_sec": 5.0, "team": "home"},
        {"time_sec": 6.0, "team": "home"},
        {"time_sec": 7.0, "team": "home"},
        {"time_sec": 8.0, "team": "home"},
        {"time_sec": 9.0, "team": "home"},
    ]
    film = [{"time_sec": 5.0, "label": "Cross", "ball_xy": [100.0, 100.0]}]
    out = estimate_crosses(film, timeline, debounce=False)
    assert out["home"]["crosses_total"] == 1
    assert out["home"]["crosses_completed"] == 1


def test_shot_splits_inside_outside_and_accuracy():
    shots = [
        {"team": "home", "time_sec": 100.0, "goal_dist": 40.0, "on_target": True},
        {"team": "home", "time_sec": 200.0, "goal_dist": 300.0, "on_target": False},
        {"team": "away", "time_sec": 300.0, "goal_dist": 50.0, "on_target": False},
    ]
    film = [
        {"time_sec": 201.0, "label": "Out", "ball_xy": [640.0, 10.0]},
        {"time_sec": 298.0, "label": "Pass", "ball_xy": [600.0, 100.0]},
    ]
    out = estimate_shot_splits(shots, film, frame_h=720.0)
    assert out["home"]["shots"] == 2
    assert out["home"]["shots_on_target"] == 1
    assert out["home"]["shots_inside_box"] == 1
    assert out["home"]["shots_outside_box"] == 1
    assert out["home"]["blocked_shots"] == 1
    assert out["home"]["shot_accuracy"] == 50.0
    assert out["away"]["key_passes"] == 1


def test_merge_remnants_fills_blanks_keeps_facts():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p10")
    # EXAMPLE facts often already have corners; force throw_ins empty.
    sheet["teams"][0]["throw_ins"] = None
    sheet["teams"][0]["sections"]["match"]["throw_ins"] = None
    remnants = build_remnants(
        film_events=[
            {"time_sec": 10.0, "label": "Throw In", "ball_xy": [50.0, 200.0]},
            {"time_sec": 20.0, "label": "Cross", "ball_xy": [100.0, 100.0]},
            {"time_sec": 30.0, "label": "High Pass", "ball_xy": [200.0, 200.0]},
        ],
        timeline=[
            {"time_sec": 10.0, "team": "home"},
            {"time_sec": 12.0, "team": "home"},
            {"time_sec": 14.0, "team": "home"},
            {"time_sec": 20.0, "team": "home"},
            {"time_sec": 22.0, "team": "home"},
            {"time_sec": 24.0, "team": "home"},
            {"time_sec": 30.0, "team": "away"},
            {"time_sec": 32.0, "team": "away"},
            {"time_sec": 34.0, "team": "away"},
        ],
        selected_shots=[
            {"team": "home", "time_sec": 40.0, "goal_dist": 50.0, "on_target": True},
        ],
        frame_h=720.0,
    )
    merged = merge_remnants_into_sheet(sheet, remnants)
    home = merged["teams"][0]
    assert home["throw_ins"] == 1
    assert home["crosses_total"] == 1
    assert home["shot_accuracy"] == 100.0
    assert home["shots_inside_box"] == 1
    assert merged["source"]["phase"] == "match-pack-phase10"
    assert merged["source"]["coverage"]["phase10"]["throw_ins_home"] == 1
    # Fouls remain unfilled.
    assert home.get("fouls_committed") is None
