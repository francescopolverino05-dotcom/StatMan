"""Spend cap, cancel-before-every-call, retag policy, partial results, scorebug fallback. Offline only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

from statman.autotag import budget, jobs, quality, scorebug, store
from statman.autotag.repo import FileEventRepo
from statman.autotag.tagger import VisionLLMTagger

from tests.test_autotag_quality import GOOD, CONDENSED, ScriptedTagger, passes  # noqa: F401


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in list(quality.DEFAULTS) + ["STATMAN_RETAG_MAX", "STATMAN_JOB_MAX_COST", "STATMAN_TEST_MAX_COST",
                                       "STATMAN_QUALITY", "STATMAN_REVIEW_THRESHOLD", "DATABASE_URL",
                                       "TAGGER_API_KEY", "TAGGER_API_URL", "TAGGER_VIDEO_FPS", "TAGGER_MAX_TOKENS",
                                       "STATMAN_SCOREBUG_LLM_MAX_CALLS"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STATMAN_SCOREBUG", "off")
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")


@pytest.fixture(scope="module")
def video_60s(tmp_path_factory) -> Path:  # 3 x 60 s clips
    out = tmp_path_factory.mktemp("atb") / "synthetic_180s.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=5", "-t", "180",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


# --- cost model / cap ------------------------------------------------------

def test_cost_estimate_per_clip():
    e2 = budget.estimate_call(60, fps=2)
    assert e2["prompt_tokens"] == 2600 + 120 * 290 and 0.02 <= e2["cost_usd"] <= 0.03
    e5 = budget.estimate_call(60, fps=5)
    assert e5["prompt_tokens"] == pytest.approx(89_600, rel=0.01)  # what the nsat1600b run billed


def test_job_cap_precedence(monkeypatch):
    assert budget.job_cap(180) == 0.40
    assert budget.job_cap(5400) == 4.0
    assert budget.job_cap(180, 0.1) == 0.1
    monkeypatch.setenv("STATMAN_TEST_MAX_COST", "0.25")
    assert budget.job_cap(180) == 0.25
    monkeypatch.setenv("STATMAN_JOB_MAX_COST", "0.2")
    assert budget.job_cap(180) == 0.2 and budget.job_cap(5400) == 0.2


def test_guard_blocks_before_call():
    g = budget.JobGuard(0.3, spent=lambda: 0.2)
    g.before_call("x", 0.05)
    with pytest.raises(budget.BudgetExceeded, match="budget"):
        g.before_call("x", 0.15)
    with pytest.raises(budget.JobCancelled):
        budget.JobGuard(1, cancelled=lambda: True).before_call("x")


def test_vision_tagger_calls_guard_before_http(tmp_path):
    hits = []
    t = VisionLLMTagger(api_url="http://x", api_key="k", model="m",
                        client=httpx.Client(transport=httpx.MockTransport(lambda r: hits.append(1))))

    def stop(kind, est):
        raise budget.BudgetExceeded(f"budget before {kind}")

    t.before_call = stop
    from statman.autotag.clips import Clip

    with pytest.raises(budget.JobStopped):
        t._call({"x": 1}, "clip 0", 60)
    assert hits == []  # no HTTP request went out
    assert t.estimate(60) == pytest.approx(budget.estimate_call(60, 2)["cost_usd"])
    _ = Clip


# --- job behaviour ---------------------------------------------------------

def _create(mid, video, **kw):
    return jobs.create_job(mid, video, duration=180, clip_seconds=60, overlap_seconds=0, **kw)


def test_budget_stop_keeps_partial_results(video_60s):
    _create("b1", video_60s, max_cost=0.35)
    t = ScriptedTagger([GOOD], cost=0.15)
    meta = jobs.process_job("b1", tagger=t)
    assert meta["status"] == "budget_stopped" and meta["partial"] and "budget" in meta["stop_reason"]
    assert len(t.contexts) == 2  # third clip blocked before its call: 0.30 spent + ~0.15 > 0.35
    assert meta["usage"]["cost_usd"] == pytest.approx(0.30)
    assert set(meta["clip_quality"]) == {"0", "1"}
    assert FileEventRepo().list_events("b1")  # events from the two tagged clips are saved
    assert meta["clips_with_tags"] == 2 and meta["cost_cap_usd"] == 0.35


def test_cancel_mid_retag_saves_best_attempt(video_60s):
    _create("c1", video_60s)

    class CancelAfterFirst(ScriptedTagger):
        def tag_clip(self, clip, context):
            out = super().tag_clip(clip, context)
            jobs.cancel_autotag("c1")
            return out

    t = CancelAfterFirst([CONDENSED, GOOD])
    meta = jobs.process_job("c1", tagger=t)
    assert meta["status"] == "cancelled" and meta["partial"]
    assert len(t.contexts) == 1  # the re-tag was blocked by the cancel check
    rec = meta["clip_quality"]["0"]
    assert "cancel" in rec["stop_reason"] and rec["flagged"]
    assert store.read_doc("c1", "quality")["0"]["clip"] == 0
    saved = FileEventRepo().list_events("c1")
    assert saved and all(e["review_status"] == "pending" for e in saved)


def test_not_fixable_goes_to_review_without_retag(video_60s, monkeypatch):
    monkeypatch.setenv("STATMAN_REVIEW_THRESHOLD", "0.5")
    one_team = [{**e, "team": "home"} for e in GOOD]
    _create("n1", video_60s)
    t = ScriptedTagger([one_team])
    meta = jobs.process_job("n1", tagger=t)
    assert meta["status"] == "done"
    assert len(t.contexts) == 3  # one call per clip, no re-tags
    rec = meta["clip_quality"]["0"]
    assert "team_missing" in {i["code"] for i in rec["issues"]} and rec["retag_fixable"] is False
    assert rec["retags"] == 0 and "not retag-fixable" in rec["stop_reason"] and rec["flagged"]
    assert meta["quality"]["clips_not_fixable"] == 3
    assert all(e["review_status"] == "pending" for e in FileEventRepo().list_events("n1"))


def test_default_retag_max_is_one(video_60s):
    _create("r1", video_60s)
    t = ScriptedTagger([CONDENSED])
    meta = jobs.process_job("r1", tagger=t)
    assert len(t.contexts) == 6 and meta["clip_quality"]["0"]["retags"] == 1


def test_clips_endpoint_shows_tags_and_reasons(video_60s):
    from fastapi.testclient import TestClient

    from statman.api import app

    _create("e1", video_60s)
    jobs.process_job("e1", tagger=ScriptedTagger([CONDENSED]))
    with TestClient(app) as client:
        r = client.get("/api/autotag/matches/e1/clips").json()
        assert r["count"] == 3 and "tags" not in r["clips"][0]
        c0 = r["clips"][0]
        assert c0["calls"] == 2 and c0["quality"]["reason"] and c0["quality"]["attempts"][0]["issues"]
        assert all("fixable" in i for i in c0["quality"]["issues"])
        full = client.get("/api/autotag/matches/e1/clips/0").json()
        assert full["tags"] and full["events_count"] == len(full["tags"])
        assert client.get("/api/autotag/matches/e1/clips?include_tags=true").json()["clips"][1]["tags"]
        assert client.get("/api/autotag/matches/e1/clips/9").status_code == 404


# --- score bug fallback ----------------------------------------------------

def test_scorebug_endpoint_normalised(monkeypatch):
    monkeypatch.setenv("TAGGER_API_URL", "https://openrouter.ai/api/v1")
    assert scorebug.llm_endpoint() == "https://openrouter.ai/api/v1/chat/completions"
    monkeypatch.setenv("TAGGER_API_URL", "https://openrouter.ai/api/v1/chat/completions/")
    assert scorebug.llm_endpoint() == "https://openrouter.ai/api/v1/chat/completions"


def _crops(tmp_path, n):
    import cv2
    import numpy as np

    out = []
    for i in range(n):
        f = tmp_path / f"c{i}.png"
        cv2.imwrite(str(f), np.zeros((20, 60, 3), dtype="uint8"))
        out.append((i * 5.0, f))
    return out


def test_scorebug_fallback_posts_to_chat_completions(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    monkeypatch.setenv("STATMAN_SCOREBUG", "auto")
    monkeypatch.setenv("TAGGER_API_KEY", "k")
    monkeypatch.setenv("TAGGER_API_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(scorebug, "sample_crops", lambda video, wd, step=5.0: _crops(tmp_path, 4))
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"clock": "12:00", "home": 1, "away": 0}'}}],
                                         "usage": {"cost": 0.0003}})

    res = scorebug.analyse(tmp_path / "v.mp4", reader=lambda img: {"clock": None, "score": None},
                           llm_fallback=True, llm_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert urls and all(u.endswith("/api/v1/chat/completions") for u in urls)
    assert res["llm_calls"] == 4 and res["llm_errors"] == 0


def test_scorebug_fallback_stops_on_errors_and_caps(monkeypatch, tmp_path):
    pytest.importorskip("cv2")
    monkeypatch.setenv("STATMAN_SCOREBUG", "auto")
    monkeypatch.setenv("TAGGER_API_KEY", "k")
    monkeypatch.setattr(scorebug, "sample_crops", lambda video, wd, step=5.0: _crops(tmp_path, 10))
    hits = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: hits.append(1) or httpx.Response(404)))
    res = scorebug.analyse(tmp_path / "v.mp4", reader=lambda img: {"clock": None, "score": None},
                           llm_fallback=True, llm_client=client)
    assert len(hits) == 3 and res["llm_errors"] == 3 and "HTTP 404" in res["llm_stopped"]

    calls = []

    def guard(kind, est):
        calls.append(kind)
        if len(calls) > 2:
            raise budget.BudgetExceeded("job cost budget reached")

    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        "choices": [{"message": {"content": "{}"}}], "usage": {"cost": 0.0003}})))
    res2 = scorebug.analyse(tmp_path / "v.mp4", reader=lambda img: {"clock": None, "score": None},
                            llm_fallback=True, llm_client=ok, before_llm_call=guard)
    assert res2["llm_calls"] == 2 and "budget" in res2["llm_stopped"]
    monkeypatch.setenv("STATMAN_SCOREBUG_LLM_MAX_CALLS", "1")
    res3 = scorebug.analyse(tmp_path / "v.mp4", reader=lambda img: {"clock": None, "score": None},
                            llm_fallback=True, llm_client=ok)
    assert res3["llm_calls"] == 1
