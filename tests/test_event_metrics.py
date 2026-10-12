"""Unit tests for the StatsBomb event catalog."""

from __future__ import annotations

import pandas as pd

from statman.event_metrics import team_event_catalog


def _row(type_name: str, *, period_id: int = 1, location=None, extra=None, **kwargs):
    return {
        "type_name": type_name,
        "period_id": period_id,
        "location": location,
        "extra": extra or {},
        **kwargs,
    }


def test_shot_breakdown_and_set_pieces():
    events = pd.DataFrame(
        [
            _row(
                "Shot",
                location=[110, 40],
                extra={"shot": {"outcome": {"name": "Goal"}, "body_part": {"name": "Head"}, "statsbomb_xg": 0.4}},
            ),
            _row(
                "Shot",
                location=[90, 40],
                extra={"shot": {"outcome": {"name": "Blocked"}, "body_part": {"name": "Right Foot"}}},
            ),
            _row(
                "Shot",
                location=[100, 20],
                extra={"shot": {"outcome": {"name": "Off T"}, "body_part": {"name": "Left Foot"}}},
            ),
            _row(
                "Shot",
                location=[108, 40],
                extra={"shot": {"outcome": {"name": "Saved"}, "body_part": {"name": "Right Foot"}}},
            ),
            _row(
                "Pass",
                period_id=1,
                extra={"pass": {"type": {"name": "Corner"}, "end_location": [120, 0]}},
            ),
            _row(
                "Pass",
                period_id=2,
                extra={"pass": {"type": {"name": "Corner"}, "end_location": [120, 80]}},
            ),
            _row(
                "Pass",
                period_id=1,
                extra={"pass": {"outcome": {"name": "Pass Offside"}, "end_location": [90, 40]}},
            ),
            _row("Foul Committed", extra={"foul_committed": {"card": {"name": "Yellow Card"}}}),
            _row("Foul Won"),
            _row("Bad Behaviour", extra={"bad_behaviour": {"card": {"name": "Red Card"}}}),
            _row(
                "Goal Keeper",
                extra={"goalkeeper": {"type": {"name": "Shot Faced"}}},
                player_id=1,
            ),
            _row(
                "Goal Keeper",
                extra={"goalkeeper": {"type": {"name": "Shot Saved"}}},
                player_id=1,
            ),
            _row(
                "Goal Keeper",
                extra={"goalkeeper": {"type": {"name": "Goal Conceded"}}},
                player_id=1,
            ),
            _row(
                "Pass",
                player_id=1,
                location=[10, 40],
                extra={"pass": {"type": {"name": "Goal Kick"}, "end_location": [40, 40]}},
            ),
            _row(
                "Pass",
                player_id=1,
                location=[10, 40],
                extra={
                    "pass": {
                        "end_location": [30, 40],
                        "outcome": {"name": "Incomplete"},
                    }
                },
            ),
            _row("Ball Recovery", location=[85, 40]),
            _row("Ball Recovery", location=[40, 40]),
            _row("Miscontrol"),
            _row("Block"),
            _row("Clearance"),
            _row("Interception"),
        ]
    )
    cat = team_event_catalog(events)
    assert cat["goals_raw"] == 1
    assert cat["shots_raw"] == 4
    assert cat["shots_on_target"] == 2
    assert cat["blocked_shots"] == 1
    assert cat["missed_shots"] == 1
    assert cat["headed_shots"] == 1
    assert cat["shots_inside_box"] == 2
    assert cat["shots_outside_box"] == 2
    assert cat["corners"] == {"first_half": 1, "second_half": 1, "total": 2}
    assert cat["offsides"]["total"] == 1
    assert cat["yellow_cards"] == 1
    assert cat["red_cards"] == 1
    assert cat["fouls_committed"] == 1
    assert cat["fouls_won"] == 1
    assert cat["gk_saves"] == 1
    assert cat["saves"] == 1
    assert cat["shots_faced"] == 3
    assert cat["shots_on_target_faced"] == 2
    assert cat["goals_conceded"] == 1
    assert cat["save_pct"] == 50.0
    assert cat["gk_passes_attempted"] == 2
    assert cat["gk_passes_completed"] == 1
    assert cat["gk_pass_accuracy"] == 50.0
    assert cat["high_recoveries"] == 1
    assert cat["recoveries"] == 2
    assert cat["balls_lost"] == 1
    assert cat["blocks"] == 1
    assert cat["clearances_raw"] == 1
    assert cat["interceptions_raw"] == 1


def test_open_play_passes_and_progressive():
    events = pd.DataFrame(
        [
            # open play progressive completed
            _row(
                "Pass",
                location=[50, 40],
                extra={"pass": {"end_location": [70, 40], "length": 20, "height": {"name": "Ground Pass"}}},
            ),
            # throw-in excluded from open passes
            _row(
                "Pass",
                location=[10, 0],
                extra={"pass": {"type": {"name": "Throw-in"}, "end_location": [20, 10]}},
            ),
            # cross incomplete
            _row(
                "Pass",
                location=[100, 10],
                extra={
                    "pass": {
                        "cross": True,
                        "end_location": [114, 40],
                        "outcome": {"name": "Incomplete"},
                        "length": 25,
                        "height": {"name": "High Pass"},
                    }
                },
            ),
            # key pass
            _row(
                "Pass",
                location=[90, 40],
                extra={"pass": {"end_location": [105, 40], "shot_assist": True, "assisted_shot_id": "x"}},
            ),
            # through ball when flagged
            _row(
                "Pass",
                location=[80, 40],
                extra={"pass": {"through_ball": True, "end_location": [105, 40]}},
            ),
        ]
    )
    cat = team_event_catalog(events)
    assert cat["open_passes_attempted"] == 4  # excludes throw-in
    assert cat["open_passes_completed"] == 3
    assert cat["crosses_total"] == 1
    assert cat["crosses_completed"] == 0
    assert cat["key_passes"] == 1
    assert cat["through_balls_total"] == 1
    assert cat["through_balls_completed"] == 1
    assert cat["long_balls_total"] >= 1
    assert cat["progressive_passes_attempted"] >= 1
