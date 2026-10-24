"""Auto-tag jobs: cut clips -> tag each clip -> merge -> route to review.

Jobs persist as ``.data/autotag/<match_id>/job.json`` like video jobs and run
one at a time on a single background worker thread (a FIFO queue), so a
long match never competes with another tagging run for CPU or API quota.
Per-clip tagger output is cached in ``raw_tags.json`` so a re-run resumes.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from statman.autotag import store
from statman.autotag import scorebug
from statman.autotag.clips import (
    DEFAULT_CLIP_SECONDS, DEFAULT_OVERLAP_SECONDS, Clip, clips_dir, cut_clip, plan_clips, video_to_match,
)
from statman.autotag.merge import build_timeline, review_threshold, route_for_review
from statman.autotag.repo import EventRepo, get_repo
from statman.autotag.tagger import Tagger, TaggerUnavailable, get_tagger

log = logging.getLogger("statman.autotag")

_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKER: dict[str, threading.Thread | None] = {"thread": None}
_WORKER_LOCK = threading.Lock()
TERMINAL = {"done", "error", "cancelled", "tagger_disabled"}


def _update(mid: str, /, **fields: Any) -> dict[str, Any]:
    with store.LOCK:
        meta = store.read_doc(mid, "job", {}) or {}
        meta.update(fields)
        meta["updated_at"] = time.time()
        store.write_doc(mid, "job", meta)
        return meta


def get_autotag_job(match_id: str) -> dict[str, Any] | None:
    return store.read_doc(store.check_match_id(match_id), "job")


def _probe_duration(path: Path) -> float:
    from statman.video.probe import probe_video

    return float(probe_video(path).get("duration_sec") or 0.0)


def create_job(
    match_id: str,
    video_path: str | Path,
    *,
    clip_seconds: float = DEFAULT_CLIP_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    segments: list[dict[str, Any]] | None = None,
    teams: dict[str, str] | None = None,
    tagger: str | None = None,
    duration: float | None = None,
) -> dict[str, Any]:
    store.check_match_id(match_id)
    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"video not found: {path}")
    current = get_autotag_job(match_id) or {}
    if current.get("status") in {"queued", "cutting", "tagging", "merging"}:
        raise ValueError(f"auto-tag already {current['status']} for {match_id}")
    duration = float(duration or _probe_duration(path))
    clips = plan_clips(duration, clip_seconds=clip_seconds, overlap_seconds=overlap_seconds, segments=segments)
    if not clips:
        raise ValueError("video has no duration")
    if current.get("video_path") != str(path) or current.get("clip_seconds") != clip_seconds \
            or current.get("overlap_seconds") != overlap_seconds:
        store.write_doc(match_id, "raw_tags", {})  # cached tags no longer line up with clips
    store.write_doc(match_id, "clips", [c.to_dict() for c in clips])
    return _update(
        match_id, match_id=match_id, status="queued", stage="queued", error=None, cancel_requested=False,
        video_path=str(path), duration_sec=duration, clip_seconds=clip_seconds, overlap_seconds=overlap_seconds,
        segments=segments or [], teams=teams or {}, tagger=tagger, clips_total=len(clips), clips_cut=0,
        clips_tagged=0, review_threshold=review_threshold(), created_at=time.time(),
    )


def _worker() -> None:
    while True:
        match_id = _QUEUE.get()
        try:
            process_job(match_id)
        except Exception:  # noqa: BLE001 - process_job records its own errors
            log.exception("auto-tag worker crashed on %s", match_id)
        finally:
            _QUEUE.task_done()


def enqueue(match_id: str) -> dict[str, Any]:
    with _WORKER_LOCK:
        t = _WORKER["thread"]
        if t is None or not t.is_alive():
            t = threading.Thread(target=_worker, name="statman-autotag", daemon=True)
            t.start()
            _WORKER["thread"] = t
    _QUEUE.put(match_id)
    return get_autotag_job(match_id) or {}


def start_autotag(match_id: str, video_path: str | Path, **kwargs: Any) -> dict[str, Any]:
    create_job(match_id, video_path, **kwargs)
    return enqueue(match_id)


def cancel_autotag(match_id: str) -> dict[str, Any]:
    meta = get_autotag_job(match_id)
    if meta is None:
        raise FileNotFoundError(f"no auto-tag job for {match_id}")
    if meta.get("status") in TERMINAL:
        return meta
    return _update(match_id, cancel_requested=True, stage="cancelling")


def _cancelled(match_id: str) -> bool:
    return bool((get_autotag_job(match_id) or {}).get("cancel_requested"))


def _run_scorebug(match_id: str, meta: dict[str, Any], src: Path) -> dict[str, Any]:
    """Once per match (cached in scorebug.json). Never fails the job."""

    cached = store.read_doc(match_id, "scorebug")
    if cached and cached.get("video_path") == str(src) and scorebug.mode() != "off":
        return cached
    _update(match_id, status="cutting", stage="reading score bug")
    try:
        sb = scorebug.analyse(src)
    except Exception as exc:  # noqa: BLE001
        log.warning("scorebug skipped for %s: %s", match_id, exc)
        sb = {"enabled": False, "reason": str(exc)}
    sb.pop("readings", None)
    sb["video_path"] = str(src)
    if scorebug.mode() != "off":
        store.write_doc(match_id, "scorebug", sb)
    _update(match_id, scorebug={k: sb.get(k) for k in ("enabled", "reason", "goals", "segments", "runtime_s",
                                                         "cost_usd", "llm_calls")})
    return sb


def process_job(match_id: str, *, tagger: Tagger | None = None, repo: EventRepo | None = None) -> dict[str, Any]:
    """Run a queued job to completion in this thread (the worker calls this)."""

    meta = get_autotag_job(match_id)
    if meta is None:
        raise FileNotFoundError(match_id)
    try:
        if meta.get("cancel_requested"):
            return _update(match_id, status="cancelled", stage="cancelled")
        if tagger is None:
            tagger = get_tagger(meta.get("tagger"))
        clips = [Clip.from_dict(c) for c in store.read_doc(match_id, "clips", [])]
        src = Path(meta["video_path"])
        out_dir = clips_dir(match_id)

        sb = _run_scorebug(match_id, meta, src)
        if sb.get("enabled") and not meta.get("segments"):
            # (a) clock from the score bug: same video windows, corrected match clock / period.
            segs = scorebug.clip_segments(sb)
            clips = [Clip(c.index, c.video_start, c.video_end, *video_to_match(c.video_start, segs), c.path)
                     for c in clips]
            store.write_doc(match_id, "clips", [c.to_dict() for c in clips])
            meta = _update(match_id, segments=segs, segments_source="scorebug")

        _update(match_id, status="cutting", stage="cutting clips")
        cut: list[Clip] = []
        for i, clip in enumerate(clips):
            if _cancelled(match_id):
                return _update(match_id, status="cancelled", stage="cancelled")
            cut.append(cut_clip(src, clip, out_dir))
            if i % 10 == 0 or i == len(clips) - 1:
                store.write_doc(match_id, "clips", [c.to_dict() for c in cut] + [c.to_dict() for c in clips[i + 1:]])
                _update(match_id, clips_cut=i + 1)
        store.write_doc(match_id, "clips", [c.to_dict() for c in cut])

        if not tagger.enabled():
            return _update(match_id, status="tagger_disabled", stage="clips ready; tagger not configured",
                           error="Set TAGGER_API_URL and TAGGER_MODEL to enable automatic tagging")

        _update(match_id, status="tagging", stage=f"tagging with {tagger.name}", tagger_backend=tagger.name)
        raw: dict[str, list] = store.read_doc(match_id, "raw_tags", {}) or {}
        context = {"teams": meta.get("teams") or {}, "match_id": match_id}
        failures: list[str] = []
        for i, clip in enumerate(cut):
            if _cancelled(match_id):
                return _update(match_id, status="cancelled", stage="cancelled")
            if str(clip.index) not in raw:
                try:
                    raw[str(clip.index)] = tagger.tag_clip(clip, context)
                except TaggerUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001 - keep going; clip is reported
                    failures.append(f"clip {clip.index}: {exc}")
                    continue
                store.write_doc(match_id, "raw_tags", raw)
            _update(match_id, clips_tagged=i + 1, clip_failures=failures)

        _update(match_id, status="merging", stage="merging overlapping clips")
        results = [(c, raw.get(str(c.index), [])) for c in cut]
        threshold = review_threshold()
        events = build_timeline(results, threshold=threshold)
        if sb.get("enabled"):
            # (b) confirmed goals in, (c) unbacked AI goals -> low-confidence shot candidates.
            events = route_for_review(scorebug.reconcile_goals(events, sb), threshold)
        saved = (repo or get_repo()).replace_ai_events(match_id, events)
        pending = sum(1 for e in saved if e["review_status"] == "pending")
        return _update(
            match_id, status="done", stage="done", review_threshold=threshold, events_total=len(saved),
            events_pending=pending, clip_failures=failures, finished_at=time.time(),
        )
    except TaggerUnavailable as exc:
        return _update(match_id, status="tagger_disabled", stage="tagger not configured", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("auto-tag job %s failed", match_id)
        return _update(match_id, status="error", stage="error", error=str(exc), traceback=traceback.format_exc()[-2000:])
