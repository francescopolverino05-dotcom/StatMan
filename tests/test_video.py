"""Tests for full-match video spotting helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from statman.video.probe import probe_video
from statman.video.spotter import SpotConfig, spot_actions
from statman.video.stats_from_events import stats_from_video_events
from statman.video import store
from statman.video.pipeline import get_job, upload_video


@pytest.fixture(scope="module")
def short_match_video(tmp_path_factory) -> Path:
    """Synthetic moving-scene video (stands in for a full match in tests)."""
    out = tmp_path_factory.mktemp("vid") / "full_match_stub.mp4"
    # 8 seconds of motion — enough to exercise the pipeline without a 90' file.
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "8",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out


def test_probe_full_match_metadata(short_match_video: Path):
    info = probe_video(short_match_video)
    assert info["duration_sec"] >= 7.5
    assert info["width"] == 640
    assert info["height"] == 360
    assert info["fps"] and info["fps"] > 0


def test_spot_actions_respects_duration_cap(short_match_video: Path):
    events = spot_actions(
        short_match_video,
        SpotConfig(sample_fps=2.0, max_duration_sec=150 * 60, min_gap_sec=0.5),
    )
    assert isinstance(events, list)
    for e in events:
        assert "label" in e and "time_sec" in e


def test_stats_payload_marks_full_match_scope():
    stats = stats_from_video_events(
        job_id="abc",
        probe={"filename": "match.mp4", "duration_sec": 5400, "width": 1280, "height": 720, "fps": 25},
        events=[
            {"time_sec": 10, "label": "Pass", "confidence": 0.5, "people_count": 4},
            {"time_sec": 20, "label": "Shot", "confidence": 0.4, "people_count": 5},
            {"time_sec": 30, "label": "Goal", "confidence": 0.4, "people_count": 6},
        ],
    )
    assert stats["source"]["scope"] == "full_match"
    assert stats["match"]["duration_min"] == 90.0
    assert stats["totals"]["shots"] == 2
    assert stats["totals"]["goals"] == 1
    assert stats["totals"]["xg"] is None
    assert stats["totals"]["ppda"] is None


def test_upload_and_process_job(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    with short_match_video.open("rb") as fh:
        meta = upload_video(fh, "wc_final_full.mp4")
    assert meta["scope"] == "full_match"
    assert meta["status"] == "queued"

    # Run processing synchronously for the test.
    from statman.video import pipeline

    pipeline._process(meta["job_id"], sample_fps=2.0)
    job = get_job(meta["job_id"])
    assert job is not None
    assert job["status"] == "done"
    assert job["stats"]["source"]["scope"] == "full_match"
    assert job["probe"]["duration_sec"] >= 7.5
