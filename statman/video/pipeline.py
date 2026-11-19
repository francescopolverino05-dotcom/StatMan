"""Upload a full match video, run approximate spotting, store events + stats."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from statman.video import store
from statman.video.probe import probe_video
from statman.video.spotter import SpotConfig, spot_actions
from statman.video.stats_from_events import stats_from_video_events

# Full-match broadcasts are large (often 1–3 GB at 720p).
DEFAULT_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_SAMPLE_FPS = 0.5

_BUILD_LOCK = threading.Lock()
_ACTIVE = False


def upload_video(
    fileobj: BinaryIO,
    filename: str,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> dict[str, Any]:
    """Persist a full-game upload and create a queued job record."""
    job_id = store.new_job_id()
    dest = store.upload_path(job_id, filename)
    written = 0
    with dest.open("wb") as out:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"File exceeds max upload size ({max_bytes // (1024**3)} GB). "
                    "Use a full-match file up to that limit."
                )
            out.write(chunk)

    if written == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("Empty upload")

    meta: dict[str, Any] = {
        "job_id": job_id,
        "status": "queued",
        "filename": Path(filename).name,
        "video_path": str(dest),
        "size_bytes": written,
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "probe": None,
        "progress": {"stage": "queued", "pct": 0, "time_sec": 0, "duration_sec": None},
        "scope": "full_match",
    }
    store.write_job(job_id, meta)
    return meta


def start_job(job_id: str, *, sample_fps: float = DEFAULT_SAMPLE_FPS) -> dict[str, Any]:
    """Process a queued full-match job on a background thread."""
    global _ACTIVE
    meta = store.read_job(job_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown job_id={job_id}")
    if meta.get("status") in {"running", "done"}:
        return meta

    def _run() -> None:
        global _ACTIVE
        with _BUILD_LOCK:
            # One full-match job at a time — CPU spotting is heavy for 90'+.
            while _ACTIVE:
                time.sleep(1.0)
            _ACTIVE = True
        try:
            _process(job_id, sample_fps=sample_fps)
        finally:
            with _BUILD_LOCK:
                _ACTIVE = False

    threading.Thread(target=_run, name=f"statman-video-{job_id}", daemon=True).start()
    meta = store.read_job(job_id) or meta
    return meta


def _process(job_id: str, *, sample_fps: float) -> None:
    meta = store.read_job(job_id)
    if meta is None:
        return
    meta["status"] = "running"
    meta["progress"] = {"stage": "probe", "pct": 2, "time_sec": 0, "duration_sec": None}
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)

    try:
        video_path = Path(meta["video_path"])
        probe = probe_video(video_path)
        duration = float(probe.get("duration_sec") or 0.0)
        meta["probe"] = probe
        meta["progress"] = {
            "stage": "spotting",
            "pct": 5,
            "time_sec": 0,
            "duration_sec": duration or None,
        }
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)

        def on_progress(t: float, dur: float, n_events: int) -> None:
            pct = 5
            if dur > 0:
                pct = 5 + int(90 * min(t / dur, 1.0))
            current = store.read_job(job_id) or {}
            current["progress"] = {
                "stage": "spotting",
                "pct": pct,
                "time_sec": round(t, 1),
                "duration_sec": round(dur, 1) if dur else duration or None,
                "events_so_far": n_events,
            }
            current["updated_at"] = time.time()
            store.write_job(job_id, current)

        events = spot_actions(
            video_path,
            SpotConfig(sample_fps=sample_fps),
            on_progress=on_progress,
        )
        store.write_events(job_id, events)

        meta = store.read_job(job_id) or meta
        meta["progress"] = {
            "stage": "aggregate",
            "pct": 96,
            "time_sec": duration,
            "duration_sec": duration or None,
            "events_so_far": len(events),
        }
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)

        stats = stats_from_video_events(job_id=job_id, probe=probe, events=events)
        store.write_stats(job_id, stats)

        meta = store.read_job(job_id) or meta
        meta["status"] = "done"
        meta["progress"] = {
            "stage": "done",
            "pct": 100,
            "time_sec": duration,
            "duration_sec": duration or None,
            "events_so_far": len(events),
        }
        meta["event_count"] = len(events)
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)
    except Exception as exc:  # noqa: BLE001 - persist failure on the job record
        meta = store.read_job(job_id) or meta
        meta["status"] = "error"
        meta["error"] = str(exc)
        meta["progress"] = {
            "stage": "error",
            "pct": (meta.get("progress") or {}).get("pct", 0),
            "time_sec": (meta.get("progress") or {}).get("time_sec", 0),
            "duration_sec": (meta.get("progress") or {}).get("duration_sec"),
        }
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)


def get_job(job_id: str, *, include_timeline: bool = True) -> dict[str, Any] | None:
    meta = store.read_job(job_id)
    if meta is None:
        return None
    out = dict(meta)
    if meta.get("status") == "done":
        out["stats"] = store.read_stats(job_id)
        if include_timeline:
            out["events"] = store.read_events(job_id)
    return out


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    rows = []
    for job_id in reversed(store.list_job_ids()):
        meta = store.read_job(job_id)
        if meta:
            probe = meta.get("probe") or {}
            rows.append(
                {
                    "job_id": meta["job_id"],
                    "status": meta.get("status"),
                    "filename": meta.get("filename"),
                    "created_at": meta.get("created_at"),
                    "duration_sec": probe.get("duration_sec"),
                    "event_count": meta.get("event_count"),
                    "error": meta.get("error"),
                    "scope": meta.get("scope", "full_match"),
                }
            )
        if len(rows) >= limit:
            break
    return rows
