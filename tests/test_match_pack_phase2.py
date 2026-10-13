"""Phase 2: import / merge film tags onto a match pack sheet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from statman.match_pack import store
from statman.match_pack.analyze import apply_film_to_sheet, import_film_job
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts
from statman.match_pack.film_merge import merge_film_into_sheet
from statman.match_pack.pipeline import compute_pack, create_pack, put_facts
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.video import store as video_store


@pytest.fixture()
def pack_root(tmp_path, monkeypatch):
    root = tmp_path / "match_packs"
    monkeypatch.setattr(store, "ROOT", root)
    store.ensure_root()
    return root


@pytest.fixture()
def video_root(tmp_path, monkeypatch):
    root = tmp_path / "videos"
    monkeypatch.setattr(video_store, "ROOT", root)
    video_store.ensure_root()
    return root


def _sample_film_stats(*, job_id: str = "jobfilm01") -> dict:
    return {
        "source": {
            "method": "yolo-person-ball-spotter-v1",
            "job_id": job_id,
            "detector": {"backend": "yolo"},
        },
        "totals": {
            "events": 12,
            "goals": 2,
            "shots": 5,
            "passes": 8,
            "drives": 1,
            "headers": 1,
            "tackles": 0,
            "blocks": 0,
            "outs": 1,
            "crosses": 2,
            "high_passes": 1,
            "throw_ins": 1,
            "free_kicks": 0,
        },
        "label_counts": {"Pass": 5, "Shot": 3, "Goal": 2, "Cross": 2},
        "per_90": {"shots": 5.0, "passes": 8.0},
        "match": {"duration_min": 90.0},
    }


def test_merge_film_keeps_fact_score_and_adds_film_block():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="p2")
    merged = merge_film_into_sheet(sheet, _sample_film_stats(), pack_id="p2")
    assert merged["match"]["home_score"] == 2
    assert merged["match"]["away_score"] == 0
    assert merged["film"]["totals"]["shots"] == 5
    assert merged["film"]["totals"]["passes"] == 8
    assert merged["source"]["phase"] == "match-pack-phase2"
    assert "film_shots" in merged["source"]["coverage"]["approximate_video"]
    # Team board still has no invented shot split.
    assert merged["teams"][0]["shots"] is None


def test_import_film_job_and_compute_keeps_film(pack_root, video_root):
    job_id = "abcd1234film"
    video_store.write_job(
        job_id,
        {
            "job_id": job_id,
            "status": "done",
            "filename": "match.mp4",
            "video_path": str(video_root / "uploads" / "match.mp4"),
            "detector": {"backend": "yolo"},
        },
    )
    (video_root / "uploads").mkdir(exist_ok=True)
    (video_root / "uploads" / "match.mp4").write_bytes(b"fake")
    events = [
        {"label": "Pass", "time_sec": 1.0, "detector": "yolo"},
        {"label": "Shot", "time_sec": 2.0, "detector": "yolo"},
    ]
    video_store.write_events(job_id, events)
    video_store.write_stats(
        job_id,
        _sample_film_stats(job_id=job_id),
    )

    meta = create_pack(home_team="Home", away_team="Away")
    pack_id = meta["pack_id"]
    put_facts(pack_id, EXAMPLE_FACTS)
    # Pretend video is ready with matching filename.
    meta = store.read_meta(pack_id)
    meta["video"] = {
        "filename": "match.mp4",
        "path": str(store.pack_dir(pack_id) / "video_match.mp4"),
        "status": "ready",
    }
    store.write_meta(pack_id, meta)
    (store.pack_dir(pack_id) / "video_match.mp4").write_bytes(b"fake")

    out = import_film_job(pack_id, job_id)
    assert out["status"] == "phase2_ready"
    assert out["sheet"]["film"]["totals"]["shots"] == 5
    assert out["analyze"]["video_job_id"] == job_id

    # Recompute from facts must keep film merge.
    recomputed = compute_pack(pack_id)
    assert recomputed["sheet"]["film"]["totals"]["passes"] == 8
    assert recomputed["sheet"]["match"]["home_score"] == 2
    assert recomputed["status"] == "phase2_ready"


def test_apply_film_requires_facts(pack_root):
    meta = create_pack()
    pack_id = meta["pack_id"]
    stats_path = store.pack_dir(pack_id) / "film_stats.json"
    stats_path.write_text(json.dumps(_sample_film_stats()), encoding="utf-8")
    with pytest.raises(ValueError, match="facts"):
        apply_film_to_sheet(pack_id)
