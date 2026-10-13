"""Reconcile film tags against fact events."""

from __future__ import annotations

import json

import pytest

from statman.match_pack import store
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.pipeline import create_pack, put_facts
from statman.match_pack.reconcile import (
    promote_corrected_into_facts,
    reconcile_film_with_facts,
    reconcile_pack,
)


@pytest.fixture()
def pack_root(tmp_path, monkeypatch):
    root = tmp_path / "match_packs"
    monkeypatch.setattr(store, "ROOT", root)
    store.ensure_root()
    return root


def test_reconcile_anchors_goal_and_forces_goal_count():
    facts = normalize_facts(EXAMPLE_FACTS)
    # Belgium scores at 47' and 70' in EXAMPLE_FACTS — check actual minutes
    goal_mins = [e["minute"] for e in facts["events"] if e["type"] == "goal"]
    assert goal_mins
    film_events = [
        {"label": "Goal", "time_sec": goal_mins[0] * 60 + 30, "confidence": 0.6},
        {"label": "Goal", "time_sec": 120.0, "confidence": 0.55},  # false positive
        {"label": "Shot", "time_sec": 200.0},
        {"label": "Pass", "time_sec": 210.0},
        {"label": "Throw In", "time_sec": 300.0},
    ]
    if len(goal_mins) > 1:
        film_events.append(
            {"label": "Goal", "time_sec": goal_mins[1] * 60 - 20, "confidence": 0.7}
        )
    corrected = reconcile_film_with_facts(facts, film_events)
    assert corrected["corrected_totals"]["goals"] == len(goal_mins)
    assert corrected["corrected_totals"]["goal_tags_raw"] >= len(goal_mins)
    assert corrected["corrected_totals"]["goal_tags_matched"] == len(goal_mins)
    assert all(a["matched"] for a in corrected["anchored_goals"])


def test_promote_preserves_film_corrected_through_normalize():
    facts = normalize_facts(EXAMPLE_FACTS)
    corrected = reconcile_film_with_facts(
        facts,
        [{"label": "Goal", "time_sec": 47 * 60, "confidence": 0.5}],
    )
    promoted = promote_corrected_into_facts(facts, corrected)
    again = normalize_facts(promoted)
    assert "film_corrected" in again
    assert again["film_corrected"]["match_totals"]["goals"] == again["film_corrected"][
        "match_totals"
    ].get("goals")
    # Timed events unchanged count
    assert len(again["events"]) == len(facts["events"])


def test_reconcile_pack_writes_facts(pack_root):
    meta = create_pack(home_team="A", away_team="B")
    pack_id = meta["pack_id"]
    put_facts(pack_id, EXAMPLE_FACTS)
    facts = store.read_meta(pack_id)["facts"]
    goal_min = next(e["minute"] for e in facts["events"] if e["type"] == "goal")
    events = [
        {"label": "Goal", "time_sec": goal_min * 60, "confidence": 0.9},
        {"label": "Shot", "time_sec": 10},
        {"label": "Pass", "time_sec": 20},
    ]
    (store.pack_dir(pack_id) / "film_events.json").write_text(
        json.dumps(events), encoding="utf-8"
    )
    (store.pack_dir(pack_id) / "film_stats.json").write_text(
        json.dumps(
            {
                "source": {"method": "test", "job_id": "t"},
                "totals": {
                    "events": 3,
                    "goals": 1,
                    "shots": 2,
                    "passes": 1,
                    "crosses": 0,
                    "high_passes": 0,
                    "drives": 0,
                    "headers": 0,
                    "tackles": 0,
                    "blocks": 0,
                    "throw_ins": 0,
                    "free_kicks": 0,
                    "outs": 0,
                },
                "label_counts": {},
                "per_90": {},
                "match": {},
            }
        ),
        encoding="utf-8",
    )
    out = reconcile_pack(pack_id, promote=True)
    assert out["status"] == "phase2_reconciled"
    assert out["facts"]["film_corrected"]["match_totals"]["goals"] == 2
    assert out["sheet"]["film"]["corrected"]["goal_tags_matched"] >= 1
