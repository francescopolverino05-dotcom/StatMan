"""Disk store for uploaded videos and spotting jobs under ``.data/videos/``."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / ".data" / "videos"
_LOCK = threading.Lock()

from statman.persistence.mirror import register as _register_collection  # noqa: E402
from statman.persistence.paths import configured_video_dir  # noqa: E402

# job.json / events.json / stats.json persist; uploads/ binaries never do.
_register_collection("videos", lambda: ROOT, include=lambda key: key.startswith("jobs/"))


def ensure_root() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "uploads").mkdir(exist_ok=True)
    (ROOT / "jobs").mkdir(exist_ok=True)
    return ROOT


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]


def job_dir(job_id: str) -> Path:
    path = ensure_root() / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def job_events_path(job_id: str) -> Path:
    return job_dir(job_id) / "events.json"


def job_stats_path(job_id: str) -> Path:
    return job_dir(job_id) / "stats.json"


def upload_path(job_id: str, filename: str) -> Path:
    safe = Path(filename).name.replace(" ", "_")
    video_dir = configured_video_dir()
    if video_dir is not None:
        uploads = video_dir / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        return uploads / f"{job_id}_{safe}"
    return ensure_root() / "uploads" / f"{job_id}_{safe}"


def _atomic_write_json(path: Path, payload: Any) -> None:
    """Write JSON via a temp file + replace so readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_job(job_id: str, meta: dict[str, Any]) -> None:
    path = job_meta_path(job_id)
    with _LOCK:
        _atomic_write_json(path, meta)


def read_job(job_id: str) -> dict[str, Any] | None:
    path = job_meta_path(job_id)
    if not path.exists():
        return None
    with _LOCK:
        text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def write_events(job_id: str, events: list[dict[str, Any]]) -> None:
    with _LOCK:
        _atomic_write_json(job_events_path(job_id), events)


def read_events(job_id: str) -> list[dict[str, Any]] | None:
    path = job_events_path(job_id)
    if not path.exists():
        return None
    with _LOCK:
        text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def write_stats(job_id: str, stats: dict[str, Any]) -> None:
    with _LOCK:
        _atomic_write_json(job_stats_path(job_id), stats)


def read_stats(job_id: str) -> dict[str, Any] | None:
    path = job_stats_path(job_id)
    if not path.exists():
        return None
    with _LOCK:
        text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def list_job_ids() -> list[str]:
    jobs = ensure_root() / "jobs"
    if not jobs.exists():
        return []
    return sorted(p.name for p in jobs.iterdir() if p.is_dir())
