"""Phase 7: pass completion + tackle rescore."""

from __future__ import annotations

from statman.match_pack.actions import (
    estimate_pass_completion,
    merge_actions_into_sheet,
    select_tackles,
)
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts


def test_pass_completion_from_possession_hold():
    timeline = [
        {"time_sec": 0.0, "team": "home"},
        {"time_sec": 2.0, "team": "home"},
        {"time_sec": 4.0, "team": "home"},
        {"time_sec": 10.0, "team": "away"},
        {"time_sec": 12.0, "team": "away"},
        {"time_sec": 14.0, "team": "home"},
    ]
    film = [
        {"time_sec": 1.0, "label": "Pass"},  # home keeps ball → completed
        {"time_sec": 10.5, "label": "Cross"},  # away then loses by 14 → incomplete-ish
        {"time_sec": 11.0, "label": "Pass"},
    ]
    # Disable debounce so our tiny fixture isn't collapsed.
    out = estimate_pass_completion(film, timeline, debounce=False)
    assert out["home"]["passes_attempted"] == 1
    assert out["home"]["passes_completed"] == 1
    assert out["home"]["pass_accuracy"] == 100.0
    assert out["away"]["passes_attempted"] == 2


def test_select_tackles_rate_limits_and_keeps_film_tag():
    scored = []
    for i in range(40):
        scored.append(
            {
                "time_sec": 60.0 + i * 20,
                "score": 0.9 - i * 0.01,
                "team": "home" if i % 2 == 0 else "away",
            }
        )
    film = [
        {
            "time_sec": 500.0,
            "label": "Player Successful Tackle",
            "motion": 20,
            "people_count": 12,
        }
    ]
    timeline = [{"time_sec": 500.0, "team": "away"}]
    out = select_tackles(
        scored,
        film,
        timeline,
        duration_sec=90 * 60,
        max_tackles_per_90=12,
        min_gap_sec=40,
    )
    assert out["budget"] == 12
    assert out["totals"]["match"]["tackles"] <= 13
    assert any(e.get("film_backed") for e in out["selected"])


def test_merge_actions_fills_board():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p7")
    passes = {
        "home": {"passes_attempted": 500, "passes_completed": 380, "pass_accuracy": 76.0},
        "away": {"passes_attempted": 220, "passes_completed": 90, "pass_accuracy": 40.9},
    }
    tackles = {
        "method": "test",
        "budget": 12,
        "warning": "test",
        "selected": [],
        "totals": {
            "home": {"tackles": 9},
            "away": {"tackles": 11},
            "match": {"tackles": 20},
        },
    }
    merged = merge_actions_into_sheet(sheet, passes=passes, tackles=tackles)
    home, away = merged["teams"]
    assert home["passes_completed"] == 380
    assert home["pass_accuracy"] == 76.0
    assert home["tackles"] == 9
    assert away["tackles"] == 11
    assert merged["source"]["phase"] == "match-pack-phase7"
    assert "pass_accuracy" not in merged["source"]["coverage"]["pending_later_phases"]
