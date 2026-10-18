"""One-click match-pack pipeline: film → reconcile → tracking → phases 4–9.

Runs steps sequentially in a background thread and records progress on
``meta["pipeline"]`` so the UI can show a single progress bar instead of
nine separate buttons.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from statman.match_pack import store
from statman.match_pack.analyze import (
    _process_pack,
    find_matching_video_job,
    import_film_job,
)
from statman.match_pack.gk import run_phase6
from statman.match_pack.phase3 import _process as _process_phase3
from statman.match_pack.tracking import TrackingConfig
from statman.match_pack.reconcile import reconcile_pack
from statman.match_pack.secondary import run_phase8
from statman.match_pack.shots import run_phase4
from statman.match_pack.sot import run_phase5
from statman.match_pack.actions import run_phase7
from statman.match_pack.xg_ppda import run_phase9
from statman.video.detector import yolo_status
from statman.video.pipeline import DEFAULT_SAMPLE_FPS

_LOCK = threading.Lock()
_ACTIVE_PACK: str | None = None

StepCb = Callable[[dict[str, Any]], None]

# (id, label, weight) — weights sum used for overall pct.
STEPS: list[tuple[str, str, float]] = [
    ("film", "Film tags", 25.0),
    ("reconcile", "Correct film with facts", 5.0),
    ("tracking", "Kit tracking / possession", 30.0),
    ("shots", "Score shots", 12.0),
    ("sot", "Shots on target", 5.0),
    ("gk", "Goalkeeper", 3.0),
    ("actions", "Passes + tackles", 8.0),
    ("secondary", "Defence + progressive", 7.0),
    ("xg_ppda", "xG + PPDA", 5.0),
]


def _set_pipeline(pack_id: str, **fields: Any) -> dict[str, Any]:
    meta = store.read_meta(pack_id) or {}
    pipe = dict(meta.get("pipeline") or {})
    pipe.update(fields)
    pipe["updated_at"] = time.time()
    meta["pipeline"] = pipe
    store.write_meta(pack_id, meta)
    return meta


def _pct_for(step_id: str, within: float = 0.0) -> int:
    total_w = sum(w for _, _, w in STEPS)
    done = 0.0
    for sid, _, w in STEPS:
        if sid == step_id:
            done += w * max(0.0, min(1.0, within))
            break
        done += w
    return int(round(100.0 * done / total_w))


def _has_film(pack_id: str) -> bool:
    return (store.pack_dir(pack_id) / "film_events.json").exists()


def _has_tracking(pack_id: str) -> bool:
    return (store.pack_dir(pack_id) / "tracking.json").exists()


def _has_shots(pack_id: str) -> bool:
    return (store.pack_dir(pack_id) / "shots.json").exists()


def _step_film(pack_id: str, *, sample_fps: float, force: bool) -> None:
    if _has_film(pack_id) and not force:
        return
    meta = store.read_meta(pack_id) or {}
    video = meta.get("video") or {}
    path = Path(video.get("path") or "")
    if not path.exists():
        raise ValueError("Upload a pack video before running full analysis")
    match = find_matching_video_job(video.get("filename") or path.name)
    if match is not None:
        import_film_job(pack_id, match["job_id"])
        return
    # Run spotting inline (this thread already owns the pipeline lock).
    meta = store.read_meta(pack_id) or meta
    analyze = {
        "status": "running",
        "source": "pack_video",
        "sample_fps": float(sample_fps),
        "progress": {"stage": "pipeline_film", "pct": 5},
        "detector": yolo_status(),
        "error": None,
        "cancel_requested": False,
        "updated_at": time.time(),
    }
    meta["analyze"] = analyze
    store.write_meta(pack_id, meta)
    _process_pack(pack_id, sample_fps=sample_fps)
    cur = store.read_meta(pack_id) or {}
    if (cur.get("analyze") or {}).get("status") == "error":
        raise RuntimeError((cur.get("analyze") or {}).get("error") or "Film analyze failed")
    if not _has_film(pack_id):
        raise RuntimeError("Film analyze finished without film_events.json")


def _step_reconcile(pack_id: str) -> None:
    meta = store.read_meta(pack_id) or {}
    if not meta.get("facts"):
        return  # optional if no facts yet
    if not _has_film(pack_id):
        return
    reconcile_pack(pack_id, promote=True)


def _step_tracking(pack_id: str, *, sample_fps: float, force: bool) -> None:
    if _has_tracking(pack_id) and not force:
        return
    cfg = TrackingConfig(sample_fps=sample_fps, start_sec=0.0)
    _process_phase3(pack_id, cfg)
    if not _has_tracking(pack_id):
        raise RuntimeError("Phase 3 tracking finished without tracking.json")


def _cancelled(pack_id: str) -> bool:
    meta = store.read_meta(pack_id) or {}
    return bool((meta.get("pipeline") or {}).get("cancel_requested"))


def run_full_pipeline(
    pack_id: str,
    *,
    sample_fps: float = 0.25,
    film_sample_fps: float = DEFAULT_SAMPLE_FPS,
    force: bool = False,
    on_progress: StepCb | None = None,
) -> dict[str, Any]:
    """Run the full board-fill pipeline synchronously."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")

    runners: dict[str, Callable[[], None]] = {
        "film": lambda: _step_film(pack_id, sample_fps=film_sample_fps, force=force),
        "reconcile": lambda: _step_reconcile(pack_id),
        "tracking": lambda: _step_tracking(pack_id, sample_fps=sample_fps, force=force),
        "shots": lambda: run_phase4(pack_id) if force or not _has_shots(pack_id) else None,
        "sot": lambda: run_phase5(pack_id),
        "gk": lambda: run_phase6(pack_id),
        "actions": lambda: run_phase7(pack_id),
        "secondary": lambda: run_phase8(pack_id),
        "xg_ppda": lambda: run_phase9(pack_id),
    }

    completed: list[str] = []
    try:
        for step_id, label, _w in STEPS:
            if _cancelled(pack_id):
                _set_pipeline(
                    pack_id,
                    status="cancelled",
                    step=step_id,
                    label=label,
                    progress={"stage": step_id, "pct": _pct_for(step_id), "label": label},
                    error="Cancelled",
                )
                return store.read_meta(pack_id) or meta

            # Skip expensive early steps when artifacts exist (unless force).
            if step_id == "film" and _has_film(pack_id) and not force:
                completed.append(step_id)
                continue
            if step_id == "tracking" and _has_tracking(pack_id) and not force:
                completed.append(step_id)
                continue
            if step_id == "shots" and _has_shots(pack_id) and not force:
                # Still re-run sot→xg so board is consistent, but skip rescoring.
                completed.append(step_id)
                continue

            _set_pipeline(
                pack_id,
                status="running",
                step=step_id,
                label=label,
                progress={
                    "stage": step_id,
                    "pct": _pct_for(step_id, 0.05),
                    "label": label,
                },
                completed=list(completed),
                error=None,
            )
            if on_progress:
                on_progress({"stage": step_id, "label": label, "pct": _pct_for(step_id, 0.05)})

            runners[step_id]()
            completed.append(step_id)
            _set_pipeline(
                pack_id,
                status="running",
                step=step_id,
                label=label,
                progress={
                    "stage": step_id,
                    "pct": _pct_for(step_id, 1.0),
                    "label": label,
                },
                completed=list(completed),
            )

        meta = store.read_meta(pack_id) or meta
        meta["status"] = "phase9_ready"
        meta["phase"] = "match-pack-phase9"
        store.write_meta(pack_id, meta)
        _set_pipeline(
            pack_id,
            status="done",
            step="done",
            label="Done",
            progress={"stage": "done", "pct": 100, "label": "Board ready"},
            completed=list(completed),
            error=None,
        )
        return store.read_meta(pack_id) or meta
    except Exception as exc:  # noqa: BLE001
        _set_pipeline(
            pack_id,
            status="error",
            error=str(exc),
            progress={
                "stage": "error",
                "pct": _pct_for(completed[-1], 1.0) if completed else 0,
                "label": "Failed",
            },
            completed=list(completed),
        )
        raise


def start_full_pipeline(
    pack_id: str,
    *,
    sample_fps: float = 0.25,
    film_sample_fps: float = DEFAULT_SAMPLE_FPS,
    force: bool = False,
) -> dict[str, Any]:
    """Queue the full pipeline on a background thread."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    pipe = meta.get("pipeline") or {}
    if pipe.get("status") in {"queued", "running"}:
        return meta

    _set_pipeline(
        pack_id,
        status="queued",
        step="queued",
        label="Queued",
        progress={"stage": "queued", "pct": 0, "label": "Queued"},
        completed=[],
        error=None,
        cancel_requested=False,
        config={
            "sample_fps": sample_fps,
            "film_sample_fps": film_sample_fps,
            "force": force,
        },
    )

    def _run() -> None:
        global _ACTIVE_PACK
        with _LOCK:
            while _ACTIVE_PACK is not None:
                time.sleep(0.5)
                if _cancelled(pack_id):
                    _set_pipeline(
                        pack_id,
                        status="cancelled",
                        error="Cancelled while waiting",
                    )
                    return
            _ACTIVE_PACK = pack_id
        try:
            run_full_pipeline(
                pack_id,
                sample_fps=sample_fps,
                film_sample_fps=film_sample_fps,
                force=force,
            )
        except Exception:  # noqa: BLE001 — status already written
            pass
        finally:
            with _LOCK:
                if _ACTIVE_PACK == pack_id:
                    _ACTIVE_PACK = None

    threading.Thread(
        target=_run, name=f"statman-full-pipeline-{pack_id}", daemon=True
    ).start()
    return store.read_meta(pack_id) or meta


def cancel_full_pipeline(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    pipe = dict(meta.get("pipeline") or {})
    if pipe.get("status") in {"done", "error", "cancelled", None}:
        return meta
    pipe["cancel_requested"] = True
    if pipe.get("status") == "queued":
        pipe["status"] = "cancelled"
        pipe["error"] = "Cancelled before start"
    meta["pipeline"] = pipe
    store.write_meta(pack_id, meta)
    return meta
