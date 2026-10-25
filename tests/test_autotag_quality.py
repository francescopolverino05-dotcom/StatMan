"""Quality checks + automatic re-tag. Offline only: a scripted mock tagger, no HTTP."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from statman.autotag import jobs, quality, store
from statman.autotag.clips import Clip
from statman.autotag.repo import FileEventRepo
from statman.autotag.tagger import VisionLLMTagger, clip_context_text


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in list(quality.DEFAULTS) + ["STATMAN_RETAG_MAX", "STATMAN_JOB_MAX_COST", "STATMAN_QUALITY",
                                       "STATMAN_REVIEW_THRESHOLD", "DATABASE_URL", "TAGGER_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STATMAN_SCOREBUG", "off")
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")


@pytest.fixture(scope="module")
def video_60s(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("atq") / "synthetic_60s.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=5", "-t", "60",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out


CLIP = Clip(0, 0, 60, 0, 1)


def _clock(s):
    return f"{int(s) // 60:02d}:{int(s) % 60:02d}"


def passes(n, fails=0, x=50, end=True, span=58.0):
    out = []
    for i in range(n):
        t = 1 + i * span / max(n, 1)
        out.append({"clock": _clock(t), "team": "home" if i % 2 else "away", "code": "PASS",
                    "outcome": "fail" if i < fails else "success", "player": None, "shirt": None,
                    "x1": x, "y1": 40, "x2": 60 if end else None, "y2": 30 if end else None,
                    "detail": None, "confidence": 0.9})
    return out


GOOD = passes(20, fails=3)
CONDENSED = passes(6, span=15)        # 6 passes, all success, silent from ~16 s
ALL_SUCCESS = passes(20, fails=0)
BAD_COORD = passes(20, fails=3, x=130)


def parse(code_events, clip=CLIP):
    body = {"choices": [{"message": {"content": json.dumps({"events": code_events})}}]}
    return VisionLLMTagger(api_url="x", model="m").parse_response(body, clip)


class ScriptedTagger:
    name = "scripted"

    def __init__(self, outputs, cost=0.01):
        self.outputs = list(outputs)
        self.contexts = []
        self.cost = cost
        self.last_usage = {}

    def enabled(self):
        return True

    def tag_clip(self, clip, context):
        self.contexts.append(context)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        self.last_usage = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
                           "cost_usd": self.cost}
        if isinstance(out, Exception):
            raise out
        return parse(out, clip)


def codes(q):
    return {i["code"] for i in q["hard"]}


# --- unit checks -----------------------------------------------------------

def test_good_clip_passes():
    q = quality.check_clip(parse(GOOD), 60)
    assert q["passed"] and q["score"] == 100, q


def test_condensed_clip_flags_few_passes_and_silence():
    q = quality.check_clip(parse(CONDENSED), 60)
    assert {"too_few_passes", "silent_stretch"} <= codes(q)
    assert "only 6 passes and 0 failed passes" in quality.corrective_text(q, 1)


def test_all_success_flags_fail_rate():
    assert codes(quality.check_clip(parse(ALL_SUCCESS), 60)) == {"no_failed_passes"}


def test_bad_coords_and_missing_end_points_and_clock_outside():
    assert "coords_out_of_range" in codes(quality.check_clip(parse(BAD_COORD), 60))
    assert "missing_end_points" in codes(quality.check_clip(parse(passes(20, 3, end=False)), 60))
    ev = GOOD + [{**GOOD[0], "clock": "55:00"}]
    assert "clock_outside_clip" in codes(quality.check_clip(parse(ev), 60))


def test_duplicates_save_without_shot_team_missing_cards_and_gap_clips():
    q = quality.check_clip(parse(GOOD + [GOOD[5]]), 60)
    assert "duplicates" in codes(q)
    save = {"clock": "00:30", "team": "home", "code": "SAVE", "outcome": None, "x1": 5, "y1": 50,
            "x2": 5, "y2": 50, "confidence": 0.9}
    assert "save_without_shot" in codes(quality.check_clip(parse(GOOD + [save]), 60))
    shot = {**save, "clock": "00:28", "team": "away", "code": "SHOT", "outcome": "on", "x1": 85, "x2": 100}
    assert "save_without_shot" not in codes(quality.check_clip(parse(GOOD + [shot, save]), 60))
    one_team = [{**e, "team": "home"} for e in GOOD]
    assert "team_missing" in codes(quality.check_clip(parse(one_team), 60))
    card = {**save, "code": "CARD", "outcome": "yellow"}
    q = quality.check_clip(parse(GOOD + [card]), 60)
    assert q["passed"] and [i["code"] for i in q["soft"]] == ["cards"]
    gap = [{"clock": "00:05", "team": "home", "code": "GAP", "x1": None, "y1": None, "x2": None, "y2": None,
            "detail": "replay", "confidence": 1}] + passes(3, 1, span=4)
    gap[1:] = [{**e, "clock": _clock(50 + i)} for i, e in enumerate(gap[1:])]
    assert "too_few_passes" not in codes(quality.check_clip(parse(gap), 60))
    assert codes(quality.check_clip(None, 60, error="bad json")) == {"parse_failure"}


def test_thresholds_from_env(monkeypatch):
    monkeypatch.setenv("STATMAN_QA_MIN_PASSES", "4")
    monkeypatch.setenv("STATMAN_QA_MAX_SILENCE", "60")
    assert quality.check_clip(parse(CONDENSED), 60)["passed"]


# --- retry loop ------------------------------------------------------------

def _run(video, tagger, mid="q1"):
    jobs.create_job(mid, video, duration=60)
    meta = jobs.process_job(mid, tagger=tagger)
    assert meta["status"] == "done", meta.get("error")
    return meta


def test_retry_triggers_with_corrective_prompt_and_picks_good(video_60s):
    t = ScriptedTagger([CONDENSED, GOOD])
    meta = _run(video_60s, t)
    assert len(t.contexts) == 2 and "corrective" not in t.contexts[0]
    corr = t.contexts[1]["corrective"]
    assert "only 6 passes and 0 failed passes" in corr and "misplaced" in corr
    assert corr in clip_context_text(CLIP, t.contexts[1])
    rec = meta["clip_quality"]["0"]
    assert rec["chosen_attempt"] == 1 and rec["passed"] and rec["retags"] == 1
    assert meta["quality"]["clips_retagged"] == 1 and meta["quality"]["clips_flagged"] == 0
    assert meta["usage"]["calls"] == 2 and meta["usage"]["cost_usd"] == pytest.approx(0.02)
    assert meta["usage"]["retry_cost_usd"] == pytest.approx(0.01)
    assert sum(e["type"] == "pass" for e in FileEventRepo().list_events("q1")) == 20


def test_best_attempt_kept_max_retries_and_flagging(video_60s, monkeypatch):
    monkeypatch.setenv("STATMAN_REVIEW_THRESHOLD", "0.5")
    t = ScriptedTagger([CONDENSED, ALL_SUCCESS, BAD_COORD, GOOD])
    meta = _run(video_60s, t)
    assert len(t.contexts) == 3  # 1 + STATMAN_RETAG_MAX (2)
    rec = meta["clip_quality"]["0"]
    assert rec["chosen_attempt"] == 1 and rec["flagged"] and not rec["passed"]  # ALL_SUCCESS scores best
    assert [a["attempt"] for a in rec["attempts"]] == [0, 1, 2]
    assert meta["quality"]["clips_flagged"] == 1
    events = FileEventRepo().list_events("q1")
    assert events and all(e["review_status"] == "pending" for e in events)
    assert any("pass fail rate" in r for r in events[0]["review_reason"])
    assert meta["events_pending"] == len(events)


def test_retag_max_env_zero(video_60s, monkeypatch):
    monkeypatch.setenv("STATMAN_RETAG_MAX", "0")
    t = ScriptedTagger([CONDENSED, GOOD])
    meta = _run(video_60s, t)
    assert len(t.contexts) == 1 and meta["quality"]["clips_flagged"] == 1


def test_budget_guard_stops_retries(video_60s, monkeypatch):
    monkeypatch.setenv("STATMAN_JOB_MAX_COST", "0.5")
    t = ScriptedTagger([CONDENSED, GOOD], cost=0.6)
    meta = _run(video_60s, t)
    assert len(t.contexts) == 1
    rec = meta["clip_quality"]["0"]
    assert "budget" in rec["stop_reason"] and rec["flagged"] and meta["quality"]["budget_stops"] == 1


def test_parse_failure_is_retried(video_60s):
    t = ScriptedTagger([ValueError("tagger response is not an event list"), GOOD])
    meta = _run(video_60s, t)
    rec = meta["clip_quality"]["0"]
    assert rec["attempts"][0]["issues"][0]["code"] == "parse_failure" and rec["passed"] and not meta["clip_failures"]


def test_quality_off(video_60s, monkeypatch):
    monkeypatch.setenv("STATMAN_QUALITY", "off")
    t = ScriptedTagger([CONDENSED, GOOD])
    meta = _run(video_60s, t)
    assert len(t.contexts) == 1 and meta["quality"]["clips_checked"] == 0
