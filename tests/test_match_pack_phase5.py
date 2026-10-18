"""Phase 5: SoT classification from film goalmouth / deflection cues."""

from __future__ import annotations

from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.match_pack.sot import (
    apply_sot_to_shots,
    classify_shot_sot,
    merge_sot_into_sheet,
    post_window_for_shot,
)


def test_fact_goal_always_sot():
    on, reason = classify_shot_sot(
        {"time_sec": 100, "fact_goal": True, "goal_dist": 40, "team": "home"},
        [],
    )
    assert on is True
    assert reason == "fact_goal"


def test_film_goalmouth_save_not_wide_miss():
    film = [
        {
            "time_sec": 100.0,
            "label": "Goal",
            "ball_xy": [640.0, 30.0],  # central, near top goal line
        },
        {"time_sec": 101.0, "label": "Shot", "ball_xy": [650.0, 40.0]},
    ]
    on, reason = classify_shot_sot(
        {"time_sec": 101.0, "goal_dist": 30.0, "team": "away"},
        film,
        frame_w=1280,
        frame_h=720,
    )
    assert on is True
    assert reason == "film_goalmouth_or_save"

    # Wide "Goal" tag (near sideline) should not count.
    wide = [
        {
            "time_sec": 200.0,
            "label": "Goal",
            "ball_xy": [1200.0, 30.0],  # lat ≈ 0.875
        }
    ]
    on2, reason2 = classify_shot_sot(
        {"time_sec": 201.0, "goal_dist": 30.0, "team": "away"},
        wide,
        frame_w=1280,
        frame_h=720,
    )
    assert on2 is False
    assert reason2 is None


def test_deflected_out_near_goal_line():
    film = [
        {
            "time_sec": 50.0,
            "label": "Out",
            "ball_xy": [1200.0, 8.0],  # on goal line, wide → corner
        },
        {"time_sec": 52.0, "label": "Shot", "ball_xy": [1100.0, 36.0]},
    ]
    on, reason = classify_shot_sot(
        {"time_sec": 52.0, "goal_dist": 36.0, "team": "home"},
        film,
        frame_w=1280,
        frame_h=720,
    )
    assert on is True
    assert reason == "deflected_or_corner"


def test_long_range_post_window_stretches():
    close = post_window_for_shot({"goal_dist": 40.0})
    far = post_window_for_shot({"goal_dist": 490.0})  # Favicchio-style
    assert far > close
    assert far >= 12.0


def test_long_range_ball_at_goalmouth_after_shot():
    """Favicchio-style: distant shot, later Cross/Shot with ball at the posts.

    Old ±6s Goal/Out-only classifier missed this; asymmetric post window +
    label-agnostic goalmouth ball should recover it.
    """
    film = [
        {"time_sec": 3515.8, "label": "Shot", "ball_xy": [700.0, 500.0]},
        # ~8s later — outside the old 6s window — ball at goalmouth after save.
        {
            "time_sec": 3523.5,
            "label": "Cross",
            "ball_xy": [640.0, 22.0],
        },
    ]
    on, reason = classify_shot_sot(
        {"time_sec": 3515.8, "goal_dist": 490.0, "team": "home"},
        film,
        frame_w=1280,
        frame_h=720,
    )
    assert on is True
    assert reason == "film_ball_at_goalmouth"

    # Same cue *before* the shot must not count (build-up).
    early = [
        {"time_sec": 3510.0, "label": "Cross", "ball_xy": [640.0, 22.0]},
        {"time_sec": 3515.8, "label": "Shot", "ball_xy": [700.0, 500.0]},
    ]
    on2, reason2 = classify_shot_sot(
        {"time_sec": 3515.8, "goal_dist": 490.0, "team": "home"},
        early,
        frame_w=1280,
        frame_h=720,
    )
    assert on2 is False
    assert reason2 is None


def test_delayed_goal_tag_outside_old_six_second_window():
    film = [
        {
            "time_sec": 112.0,
            "label": "Goal",
            "ball_xy": [640.0, 28.0],
        }
    ]
    # 10s after a long-range shot — old symmetric 6s window would miss.
    on, reason = classify_shot_sot(
        {"time_sec": 100.0, "goal_dist": 280.0, "team": "away"},
        film,
        frame_w=1280,
        frame_h=720,
    )
    assert on is True
    assert reason == "film_goalmouth_or_save"


def test_apply_sot_preserves_shot_counts():
    shot_result = {
        "method": "yolo-shot-rescore-topk-v1",
        "budget": 12,
        "selected": [
            {
                "time_sec": 100.0,
                "team": "home",
                "goal_dist": 40.0,
                "on_target": False,
                "fact_goal": True,
            },
            {
                "time_sec": 200.0,
                "team": "away",
                "goal_dist": 30.0,
                "on_target": False,
            },
            {
                "time_sec": 300.0,
                "team": "home",
                "goal_dist": 36.0,
                "on_target": False,
            },
        ],
        "totals": {
            "home": {"shots": 2, "shots_on_target": 0},
            "away": {"shots": 1, "shots_on_target": 0},
            "match": {"shots": 3, "shots_on_target": 0},
        },
    }
    film = [
        {"time_sec": 199.0, "label": "Goal", "ball_xy": [640.0, 30.0]},
        {"time_sec": 298.0, "label": "Out", "ball_xy": [1100.0, 10.0]},
    ]
    out = apply_sot_to_shots(shot_result, film, frame_w=1280, frame_h=720)
    assert out["totals"]["home"]["shots"] == 2
    assert out["totals"]["away"]["shots"] == 1
    assert out["totals"]["home"]["shots_on_target"] == 2  # fact + deflection
    assert out["totals"]["away"]["shots_on_target"] == 1  # save/goalmouth
    assert out["phase"] == "match-pack-phase5"
    assert out["method"] == "film-sot-goalmouth-v2"


def test_merge_sot_updates_board():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p5")
    shot_result = {
        "method": "film-sot-goalmouth-v2",
        "budget": 10,
        "warning": "test",
        "selected": [],
        "sot": {"window_sec": 6, "post_window_sec": 6},
        "totals": {
            "home": {"shots": 12, "shots_on_target": 2},
            "away": {"shots": 5, "shots_on_target": 1},
            "match": {"shots": 17, "shots_on_target": 3},
        },
    }
    merged = merge_sot_into_sheet(sheet, shot_result)
    home, away = merged["teams"]
    assert home["shots"] == 12
    assert home["shots_on_target"] == 2
    assert away["shots_on_target"] == 1
    assert merged["source"]["phase"] == "match-pack-phase5"
    assert merged["source"]["coverage"]["phase5"]["sot_home"] == 2
    assert home["provenance"]["shots_on_target"]["phase"] == "match-pack-phase5"
