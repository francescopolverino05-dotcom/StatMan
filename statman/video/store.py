"""Disk store for uploaded videos and spotting jobs under ``.data/videos/``."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / ".data" / "videos"
_LOCK = threading.Lock()


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
    return ensure_root() / "uploads" / f"{job_id}_{safe}"


def write_job(job_id: str, meta: dict[str, Any]) -> None:
    path = job_meta_path(job_id)
    with _LOCK:
        path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def read_job(job_id: str) -> dict[str, Any] | None:
    path = job_meta_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_events(job_id: str, events: list[dict[str, Any]]) -> None:
    with _LOCK:
        job_events_path(job_id).write_text(json.dumps(events, indent=2), encoding="utf-8")


def read_events(job_id: str) -> list[dict[str, Any]] | None:
    path = job_events_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_stats(job_id: str, stats: dict[str, Any]) -> None:
    with _LOCK:
        job_stats_path(job_id).write_text(json.dumps(stats, indent=2), encoding="utf-8")


def read_stats(job_id: str) -> dict[str, Any] | None:
    path = job_stats_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_job_ids() -> list[str]:
    jobs = ensure_root() / "jobs"
    if not jobs.exists():
        return []
    return sorted(p.name for p in jobs.iterdir() if p.is_dir())
