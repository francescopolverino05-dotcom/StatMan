"""Tests for full-match video spotting helpers."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from statman.video.probe import probe_video
from statman.video.spotter import SpotConfig, spot_actions
from statman.video.stats_from_events import stats_from_video_events
from statman.video import store
from statman.video.pipeline import (
    abort_upload,
    append_upload_chunk,
    cancel_job,
    finish_chunked_upload,
    get_job,
    init_chunked_upload,
    upload_video,
)


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
        SpotConfig(sample_fps=2.0, max_duration_sec=150 * 60, min_gap_sec=0.5, prefer_yolo=False),
    )
    assert isinstance(events, list)
    for e in events:
        assert "label" in e and "time_sec" in e


def test_spot_actions_yolo_or_fallback(short_match_video: Path):
    events = spot_actions(
        short_match_video,
        SpotConfig(sample_fps=1.0, prefer_yolo=True, min_gap_sec=0.5),
    )
    assert isinstance(events, list)


def test_stats_payload_marks_full_match_scope():
    stats = stats_from_video_events(
        job_id="abc",
        probe={"filename": "match.mp4", "duration_sec": 5400, "width": 1280, "height": 720, "fps": 25},
        events=[
            {"time_sec": 10, "label": "Pass", "confidence": 0.5, "people_count": 4, "detector": "yolo"},
            {"time_sec": 20, "label": "Shot", "confidence": 0.4, "people_count": 5, "detector": "yolo"},
            {"time_sec": 30, "label": "Goal", "confidence": 0.4, "people_count": 6, "detector": "yolo"},
        ],
        detector={"backend": "yolo", "available": True},
    )
    assert stats["source"]["scope"] == "full_match"
    assert stats["source"]["kind"] == "film_tags"
    assert stats["source"]["approximate"] is True
    assert "film action tags" in stats["source"]["note"].lower()
    assert "do not trust" not in stats["source"]["note"].lower()
    assert "match sheet" in stats["source"]["note"].lower()
    assert stats["source"]["sheet"]["path"] == "/import"
    assert stats["source"]["method"].startswith("yolo")
    assert stats["match"]["duration_min"] == 90.0
    assert stats["totals"]["shots"] == 2
    assert stats["totals"]["goals"] == 1
    # Sheet metrics must not appear as nulls on the film-tag payload.
    assert "xg" not in stats["totals"]
    assert "ppda" not in stats["totals"]
    assert "pass_accuracy" not in stats["totals"]
    assert "progressive_passes" not in stats["totals"]
    assert "aerials_won" not in stats["totals"]


def test_upload_and_process_job(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    with short_match_video.open("rb") as fh:
        meta = upload_video(fh, "wc_final_full.mp4")
    assert meta["scope"] == "full_match"
    assert meta["status"] == "queued"
    assert meta["approximate"] is True
    assert meta["warning"]

    # Run processing synchronously for the test.
    from statman.video import pipeline

    pipeline._process(meta["job_id"], sample_fps=2.0)
    job = get_job(meta["job_id"])
    assert job is not None
    assert job["status"] == "done"
    assert job["stats"]["source"]["scope"] == "full_match"
    assert job["progress"]["eta_sec"] == 0
    assert job["probe"]["duration_sec"] >= 7.5


def test_cancel_queued_job(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    with short_match_video.open("rb") as fh:
        meta = upload_video(fh, "cancel_me.mp4")
    cancelled = cancel_job(meta["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True


def test_cancel_during_process(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    with short_match_video.open("rb") as fh:
        meta = upload_video(fh, "cancel_running.mp4")

    from statman.video import pipeline

    def _cancel_soon(t, dur, n):
        if t > 0.5:
            cancel_job(meta["job_id"])

    # Patch spot_actions progress by wrapping _process cancel check via flag after start
    job_id = meta["job_id"]
    store.write_job(
        job_id,
        {**(store.read_job(job_id) or {}), "cancel_requested": True, "status": "cancelling"},
    )
    pipeline._process(job_id, sample_fps=2.0)
    job = get_job(job_id)
    assert job is not None
    assert job["status"] == "cancelled"


def test_chunked_upload_resume_and_finish(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    data = short_match_video.read_bytes()
    size = len(data)
    init = init_chunked_upload("full_match.mp4", size, chunk_bytes=1024)
    assert init["status"] == "uploading"
    assert init["bytes_received"] == 0
    assert init["chunk_bytes"] == 1024

    mid = size // 2
    first = append_upload_chunk(init["job_id"], data[:mid], offset=0)
    assert first["bytes_received"] == mid
    assert first["progress"]["upload_pct"] == int(100 * mid / size)
    assert first["progress"]["pct"] == int(first["progress"]["upload_pct"] * 0.4)

    # Wrong offset must fail so the client can re-sync.
    with pytest.raises(ValueError, match="offset mismatch"):
        append_upload_chunk(init["job_id"], data[mid : mid + 10], offset=0)

    # Resume from acknowledged offset (simulates retry after a blip).
    second = append_upload_chunk(init["job_id"], data[mid:], offset=mid)
    assert second["bytes_received"] == size
    assert second["progress"]["upload_pct"] == 100

    finished = finish_chunked_upload(init["job_id"], sample_fps=2.0, auto_start=False)
    assert finished["status"] == "queued"
    assert finished["progress"]["pct"] == 40
    assert Path(finished["video_path"]).read_bytes() == data


def test_chunked_upload_abort(short_match_video: Path, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    data = short_match_video.read_bytes()
    init = init_chunked_upload("abort_me.mp4", len(data), chunk_bytes=2048)
    append_upload_chunk(init["job_id"], data[:2048], offset=0)
    aborted = abort_upload(init["job_id"])
    assert aborted["status"] == "cancelled"
    assert not Path(init["video_path"]).exists()


def test_chunked_upload_rejects_oversized(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "ROOT", tmp_path / "videos")
    store.ensure_root()
    with pytest.raises(ValueError, match="max upload"):
        init_chunked_upload("huge.mp4", 5 * 1024 * 1024 * 1024)
