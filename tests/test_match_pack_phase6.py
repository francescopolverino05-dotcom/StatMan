"""Phase 6: GK sheet from opponent SoT + fact goals."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.gk import build_gk_totals, gk_from_sot, merge_gk_into_sheet
from statman.match_pack.sheet_from_facts import sheet_from_facts


def test_gk_from_sot_basic():
    home = gk_from_sot(opponent_sot=1, goals_conceded=0)
    assert home["shots_faced"] == 1
    assert home["shots_on_target_faced"] == 1
    assert home["saves"] == 1
    assert home["save_pct"] == 100.0

    away = gk_from_sot(opponent_sot=2, goals_conceded=1)
    assert away["shots_faced"] == 2
    assert away["saves"] == 1
    assert away["save_pct"] == 50.0


def test_gk_faced_at_least_goals_conceded():
    # Safety if SoT under-counts vs fact goals.
    row = gk_from_sot(opponent_sot=0, goals_conceded=1)
    assert row["shots_faced"] == 1
    assert row["saves"] == 0
    assert row["save_pct"] == 0.0


def test_build_and_merge_gk_board():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p6")
    # EXAMPLE is typically 2-1 style — force conceded from sheet sides.
    sheet["teams"][0]["goals_conceded"] = 0
    sheet["teams"][1]["goals_conceded"] = 1
    sheet["teams"][0]["sections"]["goalkeeper"]["goals_conceded"] = 0
    sheet["teams"][1]["sections"]["goalkeeper"]["goals_conceded"] = 1

    shot_totals = {
        "home": {"shots": 12, "shots_on_target": 2},
        "away": {"shots": 5, "shots_on_target": 1},
    }
    gk = build_gk_totals(shot_totals, sheet)
    assert gk["home"]["shots_faced"] == 1
    assert gk["home"]["saves"] == 1
    assert gk["away"]["shots_faced"] == 2
    assert gk["away"]["saves"] == 1

    merged = merge_gk_into_sheet(sheet, gk)
    home, away = merged["teams"]
    assert home["shots_faced"] == 1
    assert home["saves"] == 1
    assert home["save_pct"] == 100.0
    assert away["shots_faced"] == 2
    assert away["saves"] == 1
    assert away["sections"]["goalkeeper"]["save_pct"] == 50.0
    assert merged["source"]["phase"] == "match-pack-phase6"
    assert merged["source"]["coverage"]["phase6"]["saves_home"] == 1
