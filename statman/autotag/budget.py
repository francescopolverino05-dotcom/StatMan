"""Per-job spend cap, cancel checks before every model call, and the cost model.

Every paid model call (clip tag, internal transport/parse retry, json_object
collapse retry, quality re-tag, goal re-look, score-bug crop fallback) goes
through ``JobGuard.before_call`` first. It raises ``JobCancelled`` when the job
was cancelled and ``BudgetExceeded`` when the money already spent plus the
estimated cost of the next call would pass the job cap, so a job stops cleanly
*before* the call instead of after it.

Cap precedence (``job_cap``):

1. the per-run ``max_cost`` parameter (POST .../run body), stored in job.json;
2. runs shorter than 10 minutes of video: ``STATMAN_TEST_MAX_COST`` (default
   $0.40), never above ``STATMAN_JOB_MAX_COST`` when that is set;
3. longer runs: ``STATMAN_JOB_MAX_COST`` (default $4.00).

Cost model (google/gemini-2.5-flash through OpenRouter, calibrated on the
nsat1600b run of 2026-10-25: 6 calls at 5 fps, 89.6k prompt tokens and
5.3k-11.1k completion tokens for $0.047-0.061 each):

* Gemini bills ~290 prompt tokens per *video second* it samples (258 image
  tokens + ~32 per-second overhead; the file is time-stretched so one video
  second = one real frame). Resolution does not change this count, fps does.
  A 60 s clip at 5 fps = 300 frames = 87k tokens + ~2.6k prompt text = 89.6k.
* Effective prices from that run: ~$0.375 / M prompt tokens, ~$2.50 / M
  completion tokens (completion includes the model's reasoning tokens).

  60 s clip at 2 fps:  2.6k + 120 x 290 = 37.4k prompt  -> $0.014
                       ~5k completion (capped by TAGGER_MAX_TOKENS) -> $0.0125
                       = ~$0.027 per clip  (was ~$0.051 at 5 fps)
"""

from __future__ import annotations

import os
from typing import Any, Callable

TOKENS_PER_VIDEO_SECOND = 290
PROMPT_TEXT_TOKENS = 2600
PROMPT_USD_PER_TOKEN = 0.375e-6
COMPLETION_USD_PER_TOKEN = 2.50e-6
TYPICAL_COMPLETION_TOKENS = 5000
TEST_RUN_MAX_SECONDS = 600.0
TEST_MAX_COST_DEFAULT = 0.40
JOB_MAX_COST_DEFAULT = 4.0


class JobStopped(RuntimeError):
    """Base: the job must stop before the next model call."""


class JobCancelled(JobStopped):
    pass


class BudgetExceeded(JobStopped):
    pass


def _env_float(name: str) -> float | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def job_cap(duration_sec: float | None = None, max_cost: float | None = None) -> float:
    if max_cost is not None:
        return float(max_cost)
    job_env = _env_float("STATMAN_JOB_MAX_COST")
    if duration_sec is not None and float(duration_sec) < TEST_RUN_MAX_SECONDS:
        test = _env_float("STATMAN_TEST_MAX_COST")
        test = TEST_MAX_COST_DEFAULT if test is None else test
        return min(test, job_env) if job_env is not None else test
    return job_env if job_env is not None else JOB_MAX_COST_DEFAULT


def estimate_call(duration_s: float, fps: float = 2.0, stretch: bool = True,
                  completion_tokens: int = TYPICAL_COMPLETION_TOKENS) -> dict[str, Any]:
    """Expected tokens / USD for one tag call on ``duration_s`` seconds of real play."""

    video_seconds = float(duration_s) * (float(fps) if stretch else 1.0)
    prompt = int(PROMPT_TEXT_TOKENS + TOKENS_PER_VIDEO_SECOND * video_seconds)
    cost = prompt * PROMPT_USD_PER_TOKEN + completion_tokens * COMPLETION_USD_PER_TOKEN
    return {"frames": int(round(video_seconds)), "prompt_tokens": prompt, "completion_tokens": completion_tokens,
            "cost_usd": round(cost, 4)}


def usage_cost(rows: list[dict[str, Any]]) -> float:
    return sum(float(r.get("cost_usd") or 0.0) for r in rows)


class JobGuard:
    """Checks cancel + spend before every model call of one job run."""

    def __init__(self, cap: float, *, cancelled: Callable[[], bool] = lambda: False,
                 spent: Callable[[], float] = lambda: 0.0) -> None:
        self.cap = float(cap)
        self._cancelled = cancelled
        self._spent = spent
        self.calls_blocked = 0
        self.stop: JobStopped | None = None
        self.max_call_cost = 0.0

    def spent(self) -> float:
        return float(self._spent())

    def note_call_cost(self, cost: float | None) -> None:
        if cost:
            self.max_call_cost = max(self.max_call_cost, float(cost))

    def before_call(self, kind: str = "tag", estimate: float | None = None) -> None:
        if self._cancelled():
            self.calls_blocked += 1
            self.stop = JobCancelled(f"cancelled before {kind} call")
            raise self.stop
        spent = self.spent()
        est = float(estimate if estimate is not None else self.max_call_cost)
        if spent >= self.cap or spent + est > self.cap + 1e-9:
            self.calls_blocked += 1
            self.stop = BudgetExceeded(
                f"job cost budget ${self.cap:.2f} reached before {kind} call (spent ${spent:.3f}, next ~${est:.3f})")
            raise self.stop
