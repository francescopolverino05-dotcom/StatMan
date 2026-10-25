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
    Clip, clips_dir, cut_clip, env_clip_seconds, env_overlap_seconds, plan_clips, video_to_match,
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
    clip_seconds: float | None = None,
    overlap_seconds: float | None = None,
    segments: list[dict[str, Any]] | None = None,
    teams: dict[str, str] | None = None,
    tagger: str | None = None,
    duration: float | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    store.check_match_id(match_id)
    clip_seconds = float(clip_seconds) if clip_seconds else env_clip_seconds()
    overlap_seconds = float(overlap_seconds) if overlap_seconds is not None else env_overlap_seconds()
    if settings:
        save_settings(match_id, {**get_settings(match_id), **settings})
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
        clips_tagged=0, review_threshold=review_threshold(), created_at=time.time(), usage=None, clip_usage=[],
    )


# --- match settings (team names, kits, attacking direction) -----------------

SETTINGS_KEYS = ("home_name", "away_name", "home_kit", "away_kit", "home_attacks_first_half")


def get_settings(match_id: str) -> dict[str, Any]:
    """settings.json: {home_name, away_name, home_kit, away_kit, home_attacks_first_half: left|right}."""
    return dict(store.read_doc(store.check_match_id(match_id), "settings", {}) or {})


def clean_settings(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SETTINGS_KEYS:
        value = raw.get(key)
        if value is None or value == "":
            continue
        value = str(value).strip()
        if key == "home_attacks_first_half":
            value = value.lower()
            if value not in {"left", "right"}:
                raise ValueError("home_attacks_first_half must be 'left' or 'right' (as seen on screen)")
        out[key] = value
    return out


def save_settings(match_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    cleaned = clean_settings(settings)
    store.write_doc(store.check_match_id(match_id), "settings", cleaned)
    return cleaned


def home_attacks(settings: dict[str, Any], period: int) -> str | None:
    """Screen side home attacks in ``period``: halves alternate (1, 3 = first-half side)."""
    first = settings.get("home_attacks_first_half")
    if first not in {"left", "right"}:
        return None
    return first if int(period or 1) % 2 == 1 else ("left" if first == "right" else "right")


def tagger_context(match_id: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Per-match context for the tagger. ``home_attacks`` is filled per clip."""

    settings = get_settings(match_id)
    teams_meta = meta.get("teams") or {}
    teams = {
        "home": settings.get("home_name") or teams_meta.get("home_name") or teams_meta.get("home"),
        "away": settings.get("away_name") or teams_meta.get("away_name") or teams_meta.get("away"),
    }
    kits = {
        "home": settings.get("home_kit") or teams_meta.get("home_kit"),
        "away": settings.get("away_kit") or teams_meta.get("away_kit"),
    }
    lineups: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for p in (store.read_doc(match_id, "lineup", {}) or {}).get("players") or []:
        if isinstance(p, dict) and p.get("team") in lineups and p.get("shirt") is not None:
            lineups[p["team"]].append({"shirt": p["shirt"], "name": p.get("name")})
    return {"teams": teams, "kits": {k: v for k, v in kits.items() if v}, "lineups": lineups,
            "match_id": match_id, "settings": settings}


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


def _usage_total(clip_usage: list[dict[str, Any]]) -> dict[str, Any]:
    tot: dict[str, Any] = {"calls": len(clip_usage), "prompt_tokens": 0, "completion_tokens": 0,
                           "total_tokens": 0, "cost_usd": 0.0}
    for u in clip_usage:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            tot[key] += int(u.get(key) or 0)
        tot["cost_usd"] += float(u.get("cost_usd") or 0.0)
    tot["cost_usd"] = round(tot["cost_usd"], 6)
    if clip_usage:
        tot["cost_per_clip_usd"] = round(tot["cost_usd"] / len(clip_usage), 6)
    return tot


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
        context = tagger_context(match_id, meta)
        failures: list[str] = []
        clip_usage: list[dict[str, Any]] = list((get_autotag_job(match_id) or {}).get("clip_usage") or [])
        for i, clip in enumerate(cut):
            if _cancelled(match_id):
                return _update(match_id, status="cancelled", stage="cancelled")
            if str(clip.index) not in raw:
                clip_ctx = {**context, "home_attacks": home_attacks(context["settings"], clip.period)}
                if hasattr(tagger, "last_usage"):
                    tagger.last_usage = {}
                try:
                    raw[str(clip.index)] = tagger.tag_clip(clip, clip_ctx)
                except TaggerUnavailable:
                    raise
                except Exception as exc:  # noqa: BLE001 - keep going; clip is reported
                    failures.append(f"clip {clip.index}: {exc}")
                    continue
                finally:
                    last = getattr(tagger, "last_usage", None)
                    if last:
                        clip_usage.append({"clip": clip.index, **last})
                store.write_doc(match_id, "raw_tags", raw)
            _update(match_id, clips_tagged=i + 1, clip_failures=failures, usage=_usage_total(clip_usage),
                    clip_usage=clip_usage)

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
