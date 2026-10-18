"""Phase 9: xG heuristic + PPDA."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.match_pack.xg_ppda import (
    estimate_ppda,
    estimate_xg,
    merge_xg_ppda_into_sheet,
    shot_xg,
)


def test_shot_xg_fact_goal_high():
    assert shot_xg({"fact_goal": True, "goal_dist": 40}) >= 0.55
    far = shot_xg({"goal_dist": 250, "prox": 0.2, "toward_n": 0.5, "score": 0.6})
    close = shot_xg(
        {"goal_dist": 30, "prox": 0.9, "toward_n": 1.0, "score": 0.9, "on_target": True}
    )
    assert close > far
    assert 0.02 <= far <= 0.85
    assert close <= 0.85


def test_estimate_xg_totals():
    shots = [
        {"team": "home", "fact_goal": True, "goal_dist": 40},
        {"team": "home", "goal_dist": 50, "prox": 0.8, "toward_n": 1.0, "score": 0.9},
        {"team": "away", "goal_dist": 60, "prox": 0.7, "toward_n": 0.9, "score": 0.85},
    ]
    out = estimate_xg(shots, frame_h=720)
    assert out["totals"]["home"]["xg"] > out["totals"]["away"]["xg"]
    assert all("xg" in e for e in out["selected"])


def test_ppda_and_merge():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p9")
    sheet["teams"][0]["passes_attempted"] = 500
    sheet["teams"][1]["passes_attempted"] = 200
    sheet["teams"][0]["tackles"] = 10
    sheet["teams"][0]["interceptions"] = 5
    sheet["teams"][1]["tackles"] = 8
    sheet["teams"][1]["interceptions"] = 2
    ppda = estimate_ppda(sheet)
    # home faces 200 opp passes / 15 def actions
    assert ppda["home"]["ppda"] == round(200 / 15, 2)
    assert ppda["away"]["ppda"] == round(500 / 10, 2)

    xg = {
        "method": "test",
        "selected": [],
        "totals": {
            "home": {"xg": 1.2},
            "away": {"xg": 0.4},
            "match": {"xg": 1.6},
        },
    }
    merged = merge_xg_ppda_into_sheet(sheet, xg=xg, ppda=ppda)
    home, away = merged["teams"]
    assert home["xg"] == 1.2
    assert away["xg"] == 0.4
    assert home["ppda"] == ppda["home"]["ppda"]
    assert merged["source"]["phase"] == "match-pack-phase9"
    pending = merged["source"]["coverage"]["pending_later_phases"]
    assert "xg" not in pending
    assert "ppda" not in pending
