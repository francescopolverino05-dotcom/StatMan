"""Offline unit tests for derived StatMan metrics."""

from __future__ import annotations

import pandas as pd

from statman.compute import (
    FIELD_LENGTH,
    PPDA_OWN_ZONE_X,
    _ppda,
    _progressive_passes,
    _ratio,
    _sum_xg,
    _aerials,
)


def test_progressive_pass_by_advance():
    passes = pd.DataFrame(
        [
            {"start_x": 50.0, "end_x": 60.0, "result_name": "success"},  # ~10 m
            {"start_x": 50.0, "end_x": 55.0, "result_name": "success"},  # too short
            {"start_x": 20.0, "end_x": 40.0, "result_name": "success"},  # from own 40%
            {"start_x": 70.0, "end_x": 95.0, "result_name": "fail"},  # incomplete
        ]
    )
    out = _progressive_passes(passes)
    assert len(out) == 1
    assert float(out.iloc[0]["end_x"]) == 60.0


def test_progressive_pass_into_box():
    passes = pd.DataFrame(
        [
            {"start_x": 80.0, "end_x": 90.0, "result_name": "success"},  # into box, short advance
        ]
    )
    assert len(_progressive_passes(passes)) == 1


def test_ppda():
    team = pd.DataFrame(
        [
            {"type_name": "tackle", "start_x": 70.0},
            {"type_name": "interception", "start_x": 80.0},
            {"type_name": "foul", "start_x": 10.0},  # own half — ignored
        ]
    )
    opp = pd.DataFrame(
        [
            {"type_name": "pass", "start_x": 20.0},
            {"type_name": "pass", "start_x": 40.0},
            {"type_name": "pass", "start_x": 90.0},  # advanced — ignored
            {"type_name": "cross", "start_x": PPDA_OWN_ZONE_X - 1},
        ]
    )
    # 3 opponent passes in own 60% / 2 defensive actions
    assert _ppda(team, opp) == 1.5


def test_xg_from_extra():
    events = pd.DataFrame(
        [
            {
                "type_name": "Shot",
                "extra": {"shot": {"statsbomb_xg": 0.25}},
            },
            {
                "type_name": "Shot",
                "extra": {"shot": {"statsbomb_xg": 0.1}},
            },
            {"type_name": "Pass", "extra": {}},
        ]
    )
    assert _sum_xg(events) == 0.35


def test_aerials_lost_and_won():
    events = pd.DataFrame(
        [
            {
                "type_name": "Duel",
                "extra": {"duel": {"type": {"id": 10, "name": "Aerial Lost"}}},
            },
            {
                "type_name": "Pass",
                "extra": {"pass": {"aerial_won": True}},
            },
            {
                "type_name": "Duel",
                "extra": {"duel": {"type": {"id": 11, "name": "Tackle"}, "outcome": {"name": "Won"}}},
            },
        ]
    )
    won, lost = _aerials(events)
    assert won == 1
    assert lost == 1


def test_ratio():
    assert _ratio(3, 4) == 75.0
    assert _ratio(0, 0) is None
    assert FIELD_LENGTH == 105.0
