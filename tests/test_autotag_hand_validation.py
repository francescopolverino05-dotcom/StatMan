"""Step 6 validation: the app's stats code reproduces the hand pipeline (build3.py).

Fixture: the Napoli-Spezia hand tags (tags60, 24/10/2026), Napoli = home.
Expected values are build3.py's output on the same files.
"""

from pathlib import Path

import pytest

from statman.autotag.handtags import load_files, parse_line
from statman.autotag.stats import is_progressive, match_stats, team_csv

D = Path(__file__).parent / "fixtures" / "napoli_spezia_tags60"
TEAMS = {"Napoli": "home", "Spezia": "away"}


@pytest.fixture(scope="module")
def stats():
    ev = load_files(sorted(D.glob("*.txt")), TEAMS, supplements=[
        # build3.py keeps the two Napoli shots logged only in the old 73-77 pass
        (D / "old" / "73-77.txt", lambda e: e["code"] == "SHOT" and e["clock"] in ("75:28", "76:48"))])
    return match_stats(ev)


def test_passes_and_possession_match_hand(stats):
    h, a = stats["teams"]["home"], stats["teams"]["away"]
    assert (h["passes_completed"], h["passes"]) == (946, 1131)
    assert (a["passes_completed"], a["passes"]) == (676, 846)
    assert h["possession_pct"] == 57.2 and a["possession_pct"] == 42.8


def test_progressive_passes_match_hand(stats):
    h, a = stats["teams"]["home"], stats["teams"]["away"]
    assert (h["progressive_passes_completed"], h["progressive_passes"]) == (100, 242)
    assert (a["progressive_passes_completed"], a["progressive_passes"]) == (74, 201)
    assert h["progressive_pass_pct"] == 41.3 and a["progressive_pass_pct"] == 36.8


def test_ppda_matches_hand(stats):
    h, a = stats["teams"]["home"], stats["teams"]["away"]
    assert (h["ppda_opponent_passes"], h["ppda_defensive_actions"]) == (687, 89)
    assert (a["ppda_opponent_passes"], a["ppda_defensive_actions"]) == (922, 74)
    assert round(h["ppda"], 1) == 7.7 and round(a["ppda"], 1) == 12.5


def test_flags_and_csv(stats):
    f = stats["stat_flags"]
    assert f["xg"]["status"] == "estimated"
    assert f["passes"]["status"] == "partial" and "footage gap" in f["passes"]["reasons"][0]
    assert f["players"]["status"] == "partial"
    assert "x ≤ 60" in stats["definitions"]["ppda"]
    rows = team_csv(stats).splitlines()
    assert rows[0] == "metric,home,away,status,reason"
    prog = [r for r in rows if r.startswith("Progressive Passes")]
    assert len(prog) == 1 and "242/100 (41.3%)" in prog[0] and "201/74 (36.8%)" in prog[0]
    assert not any(r.startswith("progressive_passes_completed") for r in rows)


def test_overrides_and_overlap():
    # INTERCEPT with "tackle" in the detail is a tackle; a keeper claim is not an interception
    t = parse_line("10:00|Napoli|INTERCEPT|x|4|success|50,50||sliding tackle|0.9", TEAMS)
    c = parse_line("10:05|Napoli|INTERCEPT|GK|1|success|5,50||claim high ball|0.9", TEAMS)
    s = match_stats([{**t, "review_status": "confirmed"}, {**c, "review_status": "confirmed"}])["teams"]["home"]
    assert s["tackles"] == 1 and s["interceptions"] == 0
    # 30 m inside own half needed; 10 m from the opponent half
    assert is_progressive({"x": 10, "y": 50, "x2": 45, "y2": 50})
    assert not is_progressive({"x": 10, "y": 50, "x2": 35, "y2": 50})
    assert is_progressive({"x": 60, "y": 50, "x2": 70, "y2": 50})


def test_keeper_claim_is_not_a_save():
    sh = parse_line("20:00|Spezia|SHOT|x|9|saved|85,50||on target|0.9", TEAMS)
    sv = parse_line("20:01|Napoli|SAVE|GK|1|success|||save|0.9", TEAMS)
    cl = parse_line("30:01|Napoli|SAVE|GK|1|success|||claim cross|0.9", TEAMS)
    evs = [{**e, "review_status": "confirmed"} for e in (sh, sv, cl)]
    assert match_stats(evs)["teams"]["home"]["gk_saves"] == 1
