"""Phase 8: progressive / aerials / interceptions / clearances."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.secondary import (
    build_secondary,
    estimate_aerials,
    estimate_clearances,
    estimate_progressive_passes,
    merge_secondary_into_sheet,
)
from statman.match_pack.sheet_from_facts import sheet_from_facts


def _timeline_home_then_away() -> list[dict]:
    rows = []
    for t in range(0, 20, 2):
        rows.append({"time_sec": float(t), "team": "home"})
    for t in range(20, 40, 2):
        rows.append({"time_sec": float(t), "team": "away"})
    return rows


def test_progressive_counts_high_pass_when_held():
    timeline = _timeline_home_then_away()
    film = [
        {
            "time_sec": 4.0,
            "label": "High Pass",
            "ball_xy": [640, 100],
            "handler_xy": [640, 400],
        },
        {
            "time_sec": 6.0,
            "label": "Pass",
            "ball_xy": [640, 350],
            "handler_xy": [640, 360],  # short — not progressive
        },
    ]
    out = estimate_progressive_passes(film, timeline, frame_h=720, debounce=False)
    assert out["home"]["progressive_passes_attempted"] == 1
    assert out["home"]["progressive_passes_completed"] == 1


def test_aerials_from_headers():
    timeline = _timeline_home_then_away()
    film = [
        {"time_sec": 4.0, "label": "Header", "ball_xy": [100, 100]},
        {"time_sec": 22.0, "label": "Header", "ball_xy": [100, 100]},
    ]
    out = estimate_aerials(film, timeline, debounce=False)
    assert out["home"]["aerials_total"] == 1
    assert out["away"]["aerials_total"] == 1
    assert out["home"]["aerials_won"] >= 1


def test_clearances_out_near_goal():
    timeline = [{"time_sec": float(t), "team": "away"} for t in range(0, 30, 2)]
    film = [
        {"time_sec": 10.0, "label": "Out", "ball_xy": [640.0, 8.0]},
        {"time_sec": 12.0, "label": "Out", "ball_xy": [640.0, 300.0]},  # midfield — skip
    ]
    out = estimate_clearances(
        film, timeline, frame_h=720, duration_sec=90 * 60, debounce=False
    )
    assert out["totals"]["away"]["clearances"] == 1


def test_build_and_merge_secondary():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p8")
    timeline = _timeline_home_then_away()
    film = [
        {
            "time_sec": 4.0,
            "label": "High Pass",
            "ball_xy": [640, 80],
            "handler_xy": [640, 400],
            "motion": 10,
            "people_count": 12,
        },
        {"time_sec": 5.0, "label": "Header", "ball_xy": [200, 200], "motion": 8},
        {"time_sec": 10.0, "label": "Out", "ball_xy": [100, 10], "motion": 5},
        {"time_sec": 21.0, "label": "Pass", "ball_xy": [300, 300], "motion": 10},
    ]
    # Force a flip for interceptions around 20s
    secondary = build_secondary(film, timeline, duration_sec=90 * 60)
    assert "home" in secondary["totals"]
    merged = merge_secondary_into_sheet(sheet, secondary)
    home = merged["teams"][0]
    assert home.get("progressive_passes_attempted") is not None
    assert home.get("aerials_total") is not None
    assert merged["source"]["phase"] == "match-pack-phase8"
    pending = merged["source"]["coverage"]["pending_later_phases"]
    assert "progressive_passes" not in pending
    assert "aerials_won" not in pending
    assert "xg" in pending
    assert "ppda" in pending
