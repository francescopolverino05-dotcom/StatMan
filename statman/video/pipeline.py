"""Upload a full match video, run approximate spotting, store events + stats."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from statman.video import store
from statman.video.detector import yolo_status
from statman.video.probe import probe_video
from statman.video.spotter import SpotConfig, spot_actions
from statman.video.stats_from_events import stats_from_video_events

# Full-match broadcasts are large (often 1–3 GB at 720p).
DEFAULT_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
DEFAULT_SAMPLE_FPS = 0.5
# Chunk size for resumable browser uploads (keeps each request small).
DEFAULT_CHUNK_BYTES = 8 * 1024 * 1024

_BUILD_LOCK = threading.Lock()
_ACTIVE = False

APPROX_WARNING = (
    "This is approximate. Video tags are not Opta/StatsBomb event data — "
    "do not trust counts, xG, PPDA, or possession from this path."
)


def init_chunked_upload(
    filename: str,
    size_bytes: int,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> dict[str, Any]:
    """Create a queued job and empty file for resumable full-match upload."""
    if size_bytes <= 0:
        raise ValueError("size_bytes must be > 0")
    if size_bytes > max_bytes:
        raise ValueError(
            f"File exceeds max upload size ({max_bytes // (1024**3)} GB). "
            "Compress the match (e.g. 720p) or split is not supported — use a smaller file."
        )
    job_id = store.new_job_id()
    dest = store.upload_path(job_id, filename)
    dest.write_bytes(b"")
    meta: dict[str, Any] = {
        "job_id": job_id,
        "status": "uploading",
        "filename": Path(filename).name,
        "video_path": str(dest),
        "size_bytes": int(size_bytes),
        "bytes_received": 0,
        "chunk_bytes": int(chunk_bytes),
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "probe": None,
        "cancel_requested": False,
        "approximate": True,
        "warning": APPROX_WARNING,
        "progress": {
            "stage": "uploading",
            "pct": 0,
            "bytes_received": 0,
            "size_bytes": int(size_bytes),
            "time_sec": 0,
            "duration_sec": None,
            "eta_sec": None,
            "elapsed_sec": 0,
            "approximate": True,
        },
        "scope": "full_match",
        "detector": yolo_status(),
    }
    store.write_job(job_id, meta)
    return {
        **meta,
        "chunk_bytes": int(chunk_bytes),
        "max_bytes": max_bytes,
    }


def append_upload_chunk(
    job_id: str,
    data: bytes,
    *,
    offset: int | None = None,
) -> dict[str, Any]:
    """Append one chunk to an in-progress upload (sequential by default)."""
    meta = store.read_job(job_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown job_id={job_id}")
    if meta.get("status") not in {"uploading", "queued"}:
        raise ValueError(f"Job {job_id} is not accepting chunks (status={meta.get('status')})")
    if meta.get("cancel_requested"):
        raise ValueError("Upload was cancelled")

    expected = int(meta.get("bytes_received") or 0)
    if offset is not None and int(offset) != expected:
        raise ValueError(
            f"Chunk offset mismatch: expected {expected}, got {offset}. "
            "Retry from the last acknowledged offset."
        )
    if not data:
        raise ValueError("Empty chunk")

    dest = Path(meta["video_path"])
    size_bytes = int(meta.get("size_bytes") or 0)
    if expected + len(data) > size_bytes:
        raise ValueError(
            f"Chunk would exceed declared size ({size_bytes} bytes). "
            "Re-init the upload with the correct file size."
        )

    with dest.open("ab") as out:
        out.write(data)

    received = expected + len(data)
    meta["bytes_received"] = received
    meta["status"] = "uploading"
    upload_pct = int(100 * received / size_bytes) if size_bytes else 0
    upload_pct = min(max(upload_pct, 0), 100)
    # Upload phase maps to 0–40% of the overall bar; spotting uses the rest.
    meta["progress"] = {
        "stage": "uploading",
        "pct": int(upload_pct * 0.4),
        "upload_pct": upload_pct,
        "bytes_received": received,
        "size_bytes": size_bytes,
        "time_sec": 0,
        "duration_sec": None,
        "eta_sec": None,
        "elapsed_sec": round(time.time() - float(meta.get("created_at") or time.time()), 1),
        "approximate": True,
    }
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)
    return meta


def finish_chunked_upload(
    job_id: str,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    auto_start: bool = True,
) -> dict[str, Any]:
    """Mark a chunked upload complete and optionally start spotting."""
    meta = store.read_job(job_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown job_id={job_id}")
    if meta.get("cancel_requested") or meta.get("status") == "cancelled":
        raise ValueError("Upload was cancelled")

    dest = Path(meta["video_path"])
    actual = dest.stat().st_size if dest.exists() else 0
    expected = int(meta.get("size_bytes") or 0)
    if actual == 0:
        raise ValueError("Upload file is empty")
    if expected and actual != expected:
        raise ValueError(
            f"Upload incomplete: received {actual} of {expected} bytes. "
            "Continue sending chunks, then finish again."
        )

    meta["bytes_received"] = actual
    meta["size_bytes"] = actual
    meta["status"] = "queued"
    meta["progress"] = {
        "stage": "queued",
        "pct": 40,
        "upload_pct": 100,
        "bytes_received": actual,
        "size_bytes": actual,
        "time_sec": 0,
        "duration_sec": None,
        "eta_sec": None,
        "elapsed_sec": round(time.time() - float(meta.get("created_at") or time.time()), 1),
        "approximate": True,
    }
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)
    if auto_start:
        return start_job(job_id, sample_fps=sample_fps)
    return meta


def abort_upload(job_id: str) -> dict[str, Any]:
    """Cancel an in-progress chunked upload and remove the partial file."""
    meta = store.read_job(job_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown job_id={job_id}")
    if meta.get("status") in {"running", "done"}:
        return cancel_job(job_id)
    path = Path(meta.get("video_path") or "")
    if path.exists():
        path.unlink(missing_ok=True)
    meta["cancel_requested"] = True
    meta["status"] = "cancelled"
    meta["error"] = "Upload cancelled by user"
    meta["progress"] = {
        **(meta.get("progress") or {}),
        "stage": "cancelled",
        "approximate": True,
    }
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)
    return meta


def upload_video(
    fileobj: BinaryIO,
    filename: str,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> dict[str, Any]:
    """Persist a full-game upload in one shot and create a queued job record.

    Prefer ``init_chunked_upload`` / ``append_upload_chunk`` / ``finish_chunked_upload``
    for multi-GB browser uploads (progress + retry).
    """
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
        "bytes_received": written,
        "created_at": time.time(),
        "updated_at": time.time(),
        "error": None,
        "probe": None,
        "cancel_requested": False,
        "approximate": True,
        "warning": APPROX_WARNING,
        "progress": {
            "stage": "queued",
            "pct": 0,
            "time_sec": 0,
            "duration_sec": None,
            "eta_sec": None,
            "elapsed_sec": 0,
            "approximate": True,
        },
        "scope": "full_match",
        "detector": yolo_status(),
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
    if meta.get("status") == "cancelled":
        raise ValueError(f"Job {job_id} was cancelled")

    # Clear a prior cancel flag if re-queued after cancel before start.
    meta["cancel_requested"] = False
    meta["status"] = "queued"
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)

    def _run() -> None:
        global _ACTIVE
        with _BUILD_LOCK:
            # One full-match job at a time — CPU spotting is heavy for 90'+.
            while _ACTIVE:
                time.sleep(1.0)
                current = store.read_job(job_id) or {}
                if current.get("cancel_requested"):
                    current["status"] = "cancelled"
                    current["error"] = "Cancelled while waiting for another job"
                    current["updated_at"] = time.time()
                    store.write_job(job_id, current)
                    return
            _ACTIVE = True
        try:
            _process(job_id, sample_fps=sample_fps)
        finally:
            with _BUILD_LOCK:
                _ACTIVE = False

    threading.Thread(target=_run, name=f"statman-video-{job_id}", daemon=True).start()
    meta = store.read_job(job_id) or meta
    return meta


def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation of a queued or running job."""
    meta = store.read_job(job_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown job_id={job_id}")
    status = meta.get("status")
    if status in {"done", "error", "cancelled"}:
        return meta
    meta["cancel_requested"] = True
    if status == "queued":
        meta["status"] = "cancelled"
        meta["error"] = "Cancelled before spotting started"
        meta["progress"] = {
            **(meta.get("progress") or {}),
            "stage": "cancelled",
            "pct": (meta.get("progress") or {}).get("pct", 0),
            "approximate": True,
        }
    else:
        meta["status"] = "cancelling"
        meta["progress"] = {
            **(meta.get("progress") or {}),
            "stage": "cancelling",
            "approximate": True,
        }
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)
    return meta


def _is_cancelled(job_id: str) -> bool:
    meta = store.read_job(job_id) or {}
    return bool(meta.get("cancel_requested")) or meta.get("status") in {
        "cancelled",
        "cancelling",
    }


def _process(job_id: str, *, sample_fps: float) -> None:
    meta = store.read_job(job_id)
    if meta is None:
        return
    if meta.get("cancel_requested"):
        meta["status"] = "cancelled"
        meta["error"] = "Cancelled before spotting started"
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)
        return

    meta["status"] = "running"
    meta["approximate"] = True
    meta["warning"] = APPROX_WARNING
    meta["progress"] = {
        "stage": "probe",
        "pct": 2,
        "time_sec": 0,
        "duration_sec": None,
        "eta_sec": None,
        "elapsed_sec": 0,
        "approximate": True,
    }
    meta["updated_at"] = time.time()
    store.write_job(job_id, meta)

    spotting_started = time.time()
    try:
        video_path = Path(meta["video_path"])
        probe = probe_video(video_path)
        duration = float(probe.get("duration_sec") or 0.0)
        meta = store.read_job(job_id) or meta
        if meta.get("cancel_requested"):
            raise InterruptedError("Job cancelled")
        meta["probe"] = probe
        meta["detector"] = yolo_status()
        meta["progress"] = {
            "stage": "spotting",
            "pct": 40,
            "upload_pct": 100,
            "time_sec": 0,
            "duration_sec": duration or None,
            "eta_sec": None,
            "elapsed_sec": 0,
            "approximate": True,
        }
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)
        spotting_started = time.time()

        def on_progress(t: float, dur: float, n_events: int) -> None:
            # Spotting owns 40→96% so chunked upload progress (0→40%) stays meaningful.
            pct = 40
            if dur > 0:
                pct = 40 + int(56 * min(t / dur, 1.0))
            elapsed = time.time() - spotting_started
            frac = (t / dur) if dur and dur > 0 else 0.0
            eta = None
            if frac > 0.02:
                eta = max(0.0, (elapsed / frac) - elapsed)
            current = store.read_job(job_id) or {}
            current["progress"] = {
                "stage": "spotting",
                "pct": pct,
                "upload_pct": 100,
                "time_sec": round(t, 1),
                "duration_sec": round(dur, 1) if dur else duration or None,
                "events_so_far": n_events,
                "eta_sec": round(eta, 1) if eta is not None else None,
                "elapsed_sec": round(elapsed, 1),
                "approximate": True,
            }
            current["updated_at"] = time.time()
            store.write_job(job_id, current)

        events = spot_actions(
            video_path,
            SpotConfig(sample_fps=sample_fps),
            on_progress=on_progress,
            should_cancel=lambda: _is_cancelled(job_id),
        )
        store.write_events(job_id, events)

        meta = store.read_job(job_id) or meta
        meta["progress"] = {
            "stage": "aggregate",
            "pct": 96,
            "time_sec": duration,
            "duration_sec": duration or None,
            "events_so_far": len(events),
            "eta_sec": 0,
            "elapsed_sec": round(time.time() - spotting_started, 1),
            "approximate": True,
        }
        meta["detector"] = yolo_status()
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)

        stats = stats_from_video_events(
            job_id=job_id,
            probe=probe,
            events=events,
            detector=yolo_status(),
        )
        store.write_stats(job_id, stats)

        meta = store.read_job(job_id) or meta
        meta["status"] = "done"
        meta["progress"] = {
            "stage": "done",
            "pct": 100,
            "time_sec": duration,
            "duration_sec": duration or None,
            "events_so_far": len(events),
            "eta_sec": 0,
            "elapsed_sec": round(time.time() - spotting_started, 1),
            "approximate": True,
        }
        meta["event_count"] = len(events)
        meta["approximate"] = True
        meta["warning"] = APPROX_WARNING
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)
    except InterruptedError:
        meta = store.read_job(job_id) or meta
        meta["status"] = "cancelled"
        meta["error"] = "Cancelled by user"
        meta["progress"] = {
            "stage": "cancelled",
            "pct": (meta.get("progress") or {}).get("pct", 0),
            "time_sec": (meta.get("progress") or {}).get("time_sec", 0),
            "duration_sec": (meta.get("progress") or {}).get("duration_sec"),
            "eta_sec": None,
            "elapsed_sec": round(time.time() - spotting_started, 1),
            "approximate": True,
        }
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
            "eta_sec": None,
            "elapsed_sec": round(time.time() - spotting_started, 1),
            "approximate": True,
        }
        meta["updated_at"] = time.time()
        store.write_job(job_id, meta)


def get_job(job_id: str, *, include_timeline: bool = True) -> dict[str, Any] | None:
    meta = store.read_job(job_id)
    if meta is None:
        return None
    out = dict(meta)
    out.setdefault("approximate", True)
    out.setdefault("warning", APPROX_WARNING)
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
            progress = meta.get("progress") or {}
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
                    "approximate": True,
                    "eta_sec": progress.get("eta_sec"),
                    "pct": progress.get("pct"),
                }
            )
        if len(rows) >= limit:
            break
    return rows
