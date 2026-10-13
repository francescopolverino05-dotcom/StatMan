"""Phase 2: run or import film-tag spotting for a match pack video."""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from statman.match_pack import store
from statman.match_pack.film_merge import merge_film_into_sheet
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.video import store as video_store
from statman.video.detector import yolo_status
from statman.video.probe import probe_video
from statman.video.spotter import SpotConfig, spot_actions
from statman.video.stats_from_events import stats_from_video_events

DEFAULT_SAMPLE_FPS = 0.5

_LOCK = threading.Lock()
_ACTIVE_PACK: str | None = None


def _film_events_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_events.json"


def _film_stats_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_stats.json"


def _write_analyze(meta: dict[str, Any], analyze: dict[str, Any]) -> dict[str, Any]:
    meta["analyze"] = analyze
    meta["updated_at"] = time.time()
    store.write_meta(meta["pack_id"], meta)
    return meta


def find_matching_video_job(filename: str) -> dict[str, Any] | None:
    """Return the newest *done* ``/api/video`` job whose filename matches."""
    want = Path(filename or "").name.lower()
    if not want:
        return None
    best: dict[str, Any] | None = None
    best_t = -1.0
    root = video_store.ensure_root() / "jobs"
    if not root.exists():
        return None
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        job_path = job_dir / "job.json"
        if not job_path.exists():
            continue
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if job.get("status") != "done":
            continue
        fn = Path(job.get("filename") or "").name.lower()
        if fn != want and not fn.endswith(want) and want not in fn:
            continue
        ts = float(job.get("updated_at") or job.get("created_at") or 0)
        if ts >= best_t:
            best_t = ts
            best = job
    return best


def import_film_job(pack_id: str, video_job_id: str) -> dict[str, Any]:
    """Copy a finished film-tag job into the pack and merge onto the fact sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    job = video_store.read_job(video_job_id)
    if job is None:
        raise FileNotFoundError(f"Unknown video job_id={video_job_id}")
    if job.get("status") != "done":
        raise ValueError(f"Video job {video_job_id} is not done (status={job.get('status')})")

    events = video_store.read_events(video_job_id) or []
    stats = video_store.read_stats(video_job_id)
    if stats is None:
        probe = job.get("probe") or probe_video(Path(job["video_path"]))
        stats = stats_from_video_events(
            job_id=video_job_id,
            probe=probe,
            events=events,
            detector=job.get("detector"),
        )

    _film_events_path(pack_id).write_text(
        json.dumps(events, indent=2, default=str), encoding="utf-8"
    )
    _film_stats_path(pack_id).write_text(
        json.dumps(stats, indent=2, default=str), encoding="utf-8"
    )

    analyze = {
        "status": "done",
        "source": "imported_video_job",
        "video_job_id": video_job_id,
        "event_count": len(events),
        "progress": {"stage": "done", "pct": 100},
        "detector": job.get("detector") or stats.get("source", {}).get("detector"),
        "error": None,
        "updated_at": time.time(),
    }
    meta["analyze"] = analyze
    meta["film_stats_path"] = str(_film_stats_path(pack_id))
    meta["film_events_path"] = str(_film_events_path(pack_id))
    meta["phase"] = "match-pack-phase2"
    if meta.get("video"):
        meta["video"] = {
            **meta["video"],
            "video_job_id": video_job_id,
            "film_imported": True,
        }
    store.write_meta(pack_id, meta)
    return apply_film_to_sheet(pack_id)


def import_matching_film_job(pack_id: str) -> dict[str, Any]:
    """If a done film-tag job matches the pack video filename, import it."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    filename = video.get("filename")
    if not filename:
        raise ValueError("Pack has no video filename to match")
    job = find_matching_video_job(filename)
    if job is None:
        raise FileNotFoundError(
            f"No finished film-tag job found for filename={filename!r}. "
            "Run Analyze video, or import a job id from /video."
        )
    return import_film_job(pack_id, job["job_id"])


def apply_film_to_sheet(pack_id: str) -> dict[str, Any]:
    """Rebuild fact sheet (if needed) and merge stored film stats."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    facts = meta.get("facts")
    if not facts:
        raise ValueError("Upload match facts JSON before merging film tags")
    stats_path = _film_stats_path(pack_id)
    if not stats_path.exists():
        raise ValueError("No film stats on this pack — run Analyze or Import first")
    film_stats = json.loads(stats_path.read_text(encoding="utf-8"))
    sheet = sheet_from_facts(facts, pack_id=pack_id)
    sheet = merge_film_into_sheet(sheet, film_stats, pack_id=pack_id)
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["status"] = "phase2_ready"
    meta["phase"] = "match-pack-phase2"
    meta["coverage"] = sheet["source"]["coverage"]
    meta["error"] = None
    store.write_meta(pack_id, meta)
    return meta


def start_pack_analyze(
    pack_id: str,
    *,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    reuse_matching_job: bool = True,
) -> dict[str, Any]:
    """Start background spotting on the pack video, or import a matching job."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    if video.get("status") != "ready" and not video.get("path"):
        raise ValueError("Upload a pack video (status=ready) before analyzing")
    path = Path(video.get("path") or "")
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError("Pack video file is missing or empty")

    if reuse_matching_job:
        match = find_matching_video_job(video.get("filename") or path.name)
        if match is not None:
            return import_film_job(pack_id, match["job_id"])

    analyze = meta.get("analyze") or {}
    if analyze.get("status") in {"running", "queued"}:
        return meta

    analyze = {
        "status": "queued",
        "source": "pack_video",
        "sample_fps": float(sample_fps),
        "progress": {"stage": "queued", "pct": 0},
        "detector": yolo_status(),
        "error": None,
        "cancel_requested": False,
        "updated_at": time.time(),
    }
    meta = _write_analyze(meta, analyze)

    def _run() -> None:
        global _ACTIVE_PACK
        with _LOCK:
            while _ACTIVE_PACK is not None:
                time.sleep(1.0)
                current = store.read_meta(pack_id) or {}
                if (current.get("analyze") or {}).get("cancel_requested"):
                    a = current.get("analyze") or {}
                    a["status"] = "cancelled"
                    a["error"] = "Cancelled while waiting"
                    _write_analyze(current, a)
                    return
            _ACTIVE_PACK = pack_id
        try:
            _process_pack(pack_id, sample_fps=sample_fps)
        finally:
            with _LOCK:
                if _ACTIVE_PACK == pack_id:
                    _ACTIVE_PACK = None

    threading.Thread(target=_run, name=f"statman-pack-analyze-{pack_id}", daemon=True).start()
    return store.read_meta(pack_id) or meta


def cancel_pack_analyze(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    analyze = dict(meta.get("analyze") or {})
    status = analyze.get("status")
    if status in {"done", "error", "cancelled", None}:
        return meta
    analyze["cancel_requested"] = True
    if status == "queued":
        analyze["status"] = "cancelled"
        analyze["error"] = "Cancelled before spotting started"
        analyze["progress"] = {**(analyze.get("progress") or {}), "stage": "cancelled"}
    else:
        analyze["status"] = "cancelling"
        analyze["progress"] = {**(analyze.get("progress") or {}), "stage": "cancelling"}
    return _write_analyze(meta, analyze)


def _process_pack(pack_id: str, *, sample_fps: float) -> None:
    meta = store.read_meta(pack_id)
    if meta is None:
        return
    analyze = dict(meta.get("analyze") or {})
    if analyze.get("cancel_requested"):
        analyze["status"] = "cancelled"
        _write_analyze(meta, analyze)
        return

    analyze.update(
        {
            "status": "running",
            "progress": {"stage": "probe", "pct": 2},
            "detector": yolo_status(),
            "error": None,
        }
    )
    meta = _write_analyze(meta, analyze)

    try:
        video_path = Path((meta.get("video") or {})["path"])
        probe = probe_video(video_path)
        duration = float(probe.get("duration_sec") or 0.0)
        meta = store.read_meta(pack_id) or meta
        analyze = dict(meta.get("analyze") or {})
        if analyze.get("cancel_requested"):
            raise InterruptedError("cancelled")
        analyze["probe"] = probe
        analyze["progress"] = {
            "stage": "spotting",
            "pct": 10,
            "duration_sec": duration or None,
            "time_sec": 0,
        }
        meta = _write_analyze(meta, analyze)

        def on_progress(time_sec: float, dur_sec: float, event_count: int) -> None:
            current = store.read_meta(pack_id)
            if current is None:
                return
            a = dict(current.get("analyze") or {})
            if a.get("cancel_requested"):
                return
            dur = float(dur_sec or duration or 1)
            t = float(time_sec or 0)
            pct = 10 + int(85 * min(1.0, t / dur))
            a["progress"] = {
                "stage": "spotting",
                "pct": pct,
                "time_sec": t,
                "duration_sec": dur,
                "events_so_far": int(event_count),
            }
            a["status"] = "running"
            a["event_count"] = int(event_count)
            _write_analyze(current, a)

        def should_cancel() -> bool:
            current = store.read_meta(pack_id) or {}
            return bool((current.get("analyze") or {}).get("cancel_requested"))

        events = spot_actions(
            video_path,
            SpotConfig(sample_fps=sample_fps),
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        if should_cancel():
            raise InterruptedError("cancelled")

        det = yolo_status()
        stats = stats_from_video_events(
            job_id=f"pack:{pack_id}",
            probe={**probe, "filename": video_path.name},
            events=events,
            detector=det,
        )
        _film_events_path(pack_id).write_text(
            json.dumps(events, indent=2, default=str), encoding="utf-8"
        )
        _film_stats_path(pack_id).write_text(
            json.dumps(stats, indent=2, default=str), encoding="utf-8"
        )

        meta = store.read_meta(pack_id) or meta
        analyze = dict(meta.get("analyze") or {})
        analyze.update(
            {
                "status": "done",
                "event_count": len(events),
                "progress": {"stage": "done", "pct": 100, "duration_sec": duration},
                "detector": det,
                "error": None,
            }
        )
        meta["analyze"] = analyze
        meta["film_stats_path"] = str(_film_stats_path(pack_id))
        meta["film_events_path"] = str(_film_events_path(pack_id))
        meta["phase"] = "match-pack-phase2"
        store.write_meta(pack_id, meta)
        apply_film_to_sheet(pack_id)
    except InterruptedError:
        meta = store.read_meta(pack_id) or meta
        analyze = dict(meta.get("analyze") or {})
        analyze["status"] = "cancelled"
        analyze["error"] = "Cancelled during spotting"
        analyze["progress"] = {**(analyze.get("progress") or {}), "stage": "cancelled"}
        _write_analyze(meta, analyze)
    except Exception as exc:  # noqa: BLE001
        meta = store.read_meta(pack_id) or meta
        analyze = dict(meta.get("analyze") or {})
        analyze["status"] = "error"
        analyze["error"] = str(exc)
        analyze["progress"] = {**(analyze.get("progress") or {}), "stage": "error"}
        _write_analyze(meta, analyze)


def copy_film_artifact(src: Path, dest: Path) -> None:
    shutil.copy2(src, dest)
