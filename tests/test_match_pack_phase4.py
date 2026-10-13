"""Phase 4: shot rescoring / selection."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.match_pack.shots import merge_shots_into_sheet, select_shots


def test_select_shots_respects_budget_and_fact_goals():
    scored = []
    for i in range(40):
        scored.append(
            {
                "time_sec": 60.0 + i * 30,
                "score": 0.9 - i * 0.005,
                "team": "home" if i % 2 == 0 else "away",
                "goal_dist": 50,
                "toward_n": 0.5,
            }
        )
    fact_goals = [
        {
            "team": "home",
            "fact_minute": 74,
            "player_name": "Mané",
            "film_time_sec": 74 * 60,
        }
    ]
    out = select_shots(
        scored,
        duration_sec=90 * 60,
        fact_goals=fact_goals,
        max_shots_per_90=12,
        min_gap_sec=40,
    )
    assert out["budget"] == 12
    assert out["totals"]["match"]["shots"] <= 13  # budget + possible extra fact goal
    # SoT comes from fact goals (video SoT left off until a better model).
    assert out["totals"]["home"]["shots_on_target"] >= 1
    assert out["totals"]["away"]["shots_on_target"] == 0
    assert any(e.get("fact_goal") for e in out["selected"])


def test_merge_shots_fills_board():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p4")
    shot_result = {
        "method": "test",
        "budget": 10,
        "warning": "test",
        "selected": [],
        "totals": {
            "home": {"shots": 9, "shots_on_target": 3},
            "away": {"shots": 5, "shots_on_target": 1},
            "match": {"shots": 14, "shots_on_target": 4},
        },
    }
    merged = merge_shots_into_sheet(sheet, shot_result)
    home, away = merged["teams"]
    assert home["shots"] == 9
    assert away["shots"] == 5
    assert home["shots_on_target"] == 3
    assert home["shot_accuracy"] == 33.3
    assert merged["source"]["phase"] == "match-pack-phase4"
    assert "shots" not in merged["source"]["coverage"]["pending_later_phases"]
