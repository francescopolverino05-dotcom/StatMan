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
from statman.autotag import quality, scorebug
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
    clips = {u.get("clip") for u in clip_usage}
    if clip_usage:
        tot["cost_per_clip_usd"] = round(tot["cost_usd"] / max(len(clips), 1), 6)
        retry = [u for u in clip_usage if int(u.get("attempt") or 0) > 0]
        tot["retry_calls"] = len(retry)
        tot["retry_cost_usd"] = round(sum(float(u.get("cost_usd") or 0.0) for u in retry), 6)
    return tot


def _tag_once(tagger: Tagger, clip: Clip, ctx: dict[str, Any], clip_usage: list[dict[str, Any]],
              attempt: int) -> tuple[list[dict[str, Any]] | None, str | None]:
    if hasattr(tagger, "last_usage"):
        tagger.last_usage = {}
    try:
        return tagger.tag_clip(clip, ctx), None
    except TaggerUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - recorded as a failed attempt
        return None, str(exc)
    finally:
        last = getattr(tagger, "last_usage", None)
        if last:
            clip_usage.append({"clip": clip.index, "attempt": attempt, **last})


def _tag_with_quality(match_id: str, tagger: Tagger, clip: Clip, ctx: dict[str, Any],
                      clip_usage: list[dict[str, Any]]):
    """Tag a clip, quality-check it, and re-tag with a corrective prompt while it fails.

    Returns (best events or None, quality record or None, last error). Stops after
    ``STATMAN_RETAG_MAX`` re-tags or once job cost exceeds ``STATMAN_JOB_MAX_COST``.
    """

    events, err = _tag_once(tagger, clip, ctx, clip_usage, 0)
    if not quality.enabled():
        return events, None, err
    th = quality.thresholds()
    max_retag, max_cost = quality.retag_max(), quality.job_max_cost()
    q = quality.check_clip(events, clip.duration, error=err, th=th)
    attempts = [{"attempt": 0, "score": q["score"], "passed": q["passed"], "issues": q["hard"] + q["soft"],
                 "stats": q["stats"], "error": err}]
    best = (q, events, 0)
    stop_reason = None
    n = 0
    while not best[0]["passed"] and n < max_retag:
        if _usage_total(clip_usage)["cost_usd"] >= max_cost:
            stop_reason = f"job cost budget ${max_cost:.2f} reached"
            log.warning("auto-tag %s clip %s: %s, not re-tagging", match_id, clip.index, stop_reason)
            break
        n += 1
        _update(match_id, stage=f"re-tagging clip {clip.index} (attempt {n}/{max_retag})")
        corrective = quality.corrective_text(q, n)
        ev2, err2 = _tag_once(tagger, clip, {**ctx, "corrective": corrective}, clip_usage, n)
        q = quality.check_clip(ev2, clip.duration, error=err2, th=th)
        attempts.append({"attempt": n, "score": q["score"], "passed": q["passed"], "issues": q["hard"] + q["soft"],
                         "stats": q["stats"], "error": err2, "corrective_prompt": corrective})
        if ev2 is not None and (best[1] is None or quality.rank(q) > quality.rank(best[0])):
            best = (q, ev2, n)
        if err2 is not None:
            err = err2
    bq, bev, chosen = best
    record = {
        "clip": clip.index, "attempts": attempts, "chosen_attempt": chosen, "retags": n,
        "score": bq["score"], "passed": bq["passed"], "flagged": not bq["passed"] and bev is not None,
        "issues": bq["hard"] + bq["soft"], "reason": quality.issue_summary(bq), "stop_reason": stop_reason,
    }
    return bev, record, (None if bev is not None else err)


def quality_summary(clip_quality: dict[str, Any]) -> dict[str, Any]:
    recs = list(clip_quality.values())
    return {
        "enabled": quality.enabled(), "retag_max": quality.retag_max(), "job_max_cost_usd": quality.job_max_cost(),
        "clips_checked": len(recs),
        "clips_passed": sum(1 for r in recs if r.get("passed") and not r.get("retags")),
        "clips_retagged": sum(1 for r in recs if r.get("passed") and r.get("retags")),
        "clips_flagged": sum(1 for r in recs if r.get("flagged")),
        "retags": sum(int(r.get("retags") or 0) for r in recs),
        "budget_stops": sum(1 for r in recs if r.get("stop_reason")),
    }


def flag_failed_clips(events: list[dict[str, Any]], clip_quality: dict[str, Any], threshold: float) -> list[dict[str, Any]]:
    """Events from clips that still fail after re-tags go to the review queue with the issues as reason."""

    bad = {int(k): r for k, r in clip_quality.items() if r.get("flagged")}
    if not bad:
        return events
    for ev in events:
        hits = [bad[c] for c in ev.get("clip_ids") or [] if c in bad]
        if hits:
            ev["issues"] = list(ev.get("issues") or []) + [
                f"clip {r['clip']} quality: {r['reason']}" for r in hits if r.get("reason")]
    return route_for_review(events, threshold)


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
        clip_quality: dict[str, Any] = store.read_doc(match_id, "quality", {}) or {}
        if not any(str(c.index) in raw for c in cut):
            clip_quality = {}
        for i, clip in enumerate(cut):
            if _cancelled(match_id):
                return _update(match_id, status="cancelled", stage="cancelled")
            if str(clip.index) not in raw:
                clip_ctx = {**context, "home_attacks": home_attacks(context["settings"], clip.period)}
                events, record, err = _tag_with_quality(match_id, tagger, clip, clip_ctx, clip_usage)
                if record is not None:
                    clip_quality[str(clip.index)] = record
                    store.write_doc(match_id, "quality", clip_quality)
                if events is None:
                    failures.append(f"clip {clip.index}: {err}")
                    _update(match_id, clips_tagged=i + 1, clip_failures=failures, usage=_usage_total(clip_usage),
                            clip_usage=clip_usage, quality=quality_summary(clip_quality))
                    continue
                raw[str(clip.index)] = events
                store.write_doc(match_id, "raw_tags", raw)
            _update(match_id, clips_tagged=i + 1, clip_failures=failures, usage=_usage_total(clip_usage),
                    clip_usage=clip_usage, quality=quality_summary(clip_quality))

        _update(match_id, status="merging", stage="merging overlapping clips")
        results = [(c, raw.get(str(c.index), [])) for c in cut]
        threshold = review_threshold()
        events = build_timeline(results, threshold=threshold)
        if sb.get("enabled"):
            # (b) confirmed goals in, (c) unbacked AI goals -> low-confidence shot candidates.
            events = route_for_review(scorebug.reconcile_goals(events, sb), threshold)
        events = flag_failed_clips(events, clip_quality, threshold)
        saved = (repo or get_repo()).replace_ai_events(match_id, events)
        pending = sum(1 for e in saved if e["review_status"] == "pending")
        return _update(
            match_id, status="done", stage="done", review_threshold=threshold, events_total=len(saved),
            events_pending=pending, clip_failures=failures, finished_at=time.time(),
            quality=quality_summary(clip_quality), clip_quality=clip_quality,
        )
    except TaggerUnavailable as exc:
        return _update(match_id, status="tagger_disabled", stage="tagger not configured", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        log.exception("auto-tag job %s failed", match_id)
        return _update(match_id, status="error", stage="error", error=str(exc), traceback=traceback.format_exc()[-2000:])
