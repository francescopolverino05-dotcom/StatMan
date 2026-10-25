"""Analyst-style auto-tagger: 60 s clips, video input, code schema, overlap dedupe.

Offline only: HTTP is mocked with httpx.MockTransport; no real API calls.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from statman.autotag import jobs, store
from statman.autotag.clips import Clip, cut_clip, env_clip_seconds, env_overlap_seconds, plan_clips
from statman.autotag.merge import build_timeline
from statman.autotag.repo import FileEventRepo
from statman.autotag.stats import match_stats, player_csv, team_csv
from statman.autotag.tagger import VisionLLMTagger, clip_context_text, clock_to_clip_seconds
from statman.autotag.taxonomy import clock_to_seconds, code_json_schema, from_code_event


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in ("STATMAN_CLIP_SECONDS", "STATMAN_CLIP_OVERLAP", "TAGGER_INPUT", "TAGGER_PROMPT", "TAGGER_API_KEY",
              "TAGGER_API_URL", "TAGGER_MODEL", "DATABASE_URL", "STATMAN_VIDEO_DIR", "STATMAN_REVIEW_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("STATMAN_SCOREBUG", "off")
    monkeypatch.setenv("STATMAN_QUALITY", "off")  # quality re-tag covered in test_autotag_quality.py
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")


@pytest.fixture(scope="module")
def video_70s(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("atv2") / "synthetic_70s.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10", "-t", "70",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out


def code_ev(clock, team, code, outcome=None, x1=50, y1=50, x2=None, y2=None, shirt=None, conf=0.9, detail=None):
    return {"clock": clock, "team": team, "code": code, "player": None, "shirt": shirt, "outcome": outcome,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2, "detail": detail, "confidence": conf}


def chat(events, usage=None):
    body = {"choices": [{"message": {"content": json.dumps({"events": events})}}]}
    if usage is not None:
        body["usage"] = usage
    return body


# --- clip length config ----------------------------------------------------

def test_clip_defaults_are_60s_with_5s_overlap():
    assert env_clip_seconds() == 60 and env_overlap_seconds() == 5
    clips = plan_clips(180)
    assert [c.video_start for c in clips] == [0, 55, 110, 165]
    assert all(c.duration == 60 for c in clips[:3]) and clips[-1].video_end == 180


def test_clip_length_from_env(monkeypatch):
    monkeypatch.setenv("STATMAN_CLIP_SECONDS", "30")
    monkeypatch.setenv("STATMAN_CLIP_OVERLAP", "3")
    assert [c.video_start for c in plan_clips(60)] == [0, 27, 54]
    monkeypatch.setenv("STATMAN_CLIP_SECONDS", "junk")
    monkeypatch.setenv("STATMAN_CLIP_OVERLAP", "99")  # >= clip length -> safe default
    assert env_clip_seconds() == 60 and env_overlap_seconds() == 5


def test_job_uses_env_clip_length(video_70s, monkeypatch):
    meta = jobs.create_job("cfg1", video_70s, duration=70)
    assert meta["clip_seconds"] == 60 and meta["overlap_seconds"] == 5 and meta["clips_total"] == 2
    monkeypatch.setenv("STATMAN_CLIP_SECONDS", "20")
    meta = jobs.create_job("cfg2", video_70s, duration=70)
    assert meta["clip_seconds"] == 20 and meta["clips_total"] == 5


# --- video payload ---------------------------------------------------------

def test_video_payload_is_base64_mp4_data_url(video_70s, tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=chat(
            [code_ev("00:12", "home", "PASS", "fail", 40, 30, 60, 80, detail="misplaced")],
            usage={"prompt_tokens": 15800, "completion_tokens": 900, "total_tokens": 16700, "cost": 0.007},
        ))

    t = VisionLLMTagger(api_url="http://tagger.test/api/v1", api_key="k", model="google/gemini-2.5-flash",
                        client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert t.input_mode == "video" and t.analyst
    clip = cut_clip(video_70s, plan_clips(70)[0], tmp_path)
    ctx = {"teams": {"home": "Napoli", "away": "Bari"}, "kits": {"home": "light blue", "away": "white"},
           "home_attacks": "right", "lineups": {"home": [{"shirt": 9, "name": "Lukaku"}], "away": []}}
    out = t.tag_clip(clip, ctx)

    body = seen["body"]
    parts = body["messages"][1]["content"]
    video = [p for p in parts if p["type"] == "video_url"]
    assert len(video) == 1 and not [p for p in parts if p["type"] == "image_url"]
    url = video[0]["video_url"]["url"]
    assert url.startswith("data:video/mp4;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw[4:8] == b"ftyp" and len(raw) < clip_file_size(clip)  # real mp4, re-encoded smaller
    intro = parts[0]["text"]
    assert "Napoli" in intro and "light blue" in intro and "RIGHT" in intro and "9 Lukaku" in intro
    assert "00:00" in intro  # clip start match clock
    assert body["response_format"]["json_schema"]["schema"] == code_json_schema()
    assert "EVERY" in body["messages"][0]["content"] and "RECOVERY" in body["messages"][0]["content"]
    assert seen["auth"] == "Bearer k" and "k" not in json.dumps(body["model"])
    assert out[0]["type"] == "pass" and out[0]["attributes"]["completed"] is False
    assert (out[0]["x2"], out[0]["y2"], out[0]["outcome"], out[0]["t_clip_seconds"]) == (60, 80, "fail", 12.0)
    assert t.usage_total["prompt_tokens"] == 15800 and t.usage_total["cost_usd"] == 0.007
    assert t.last_usage == {"prompt_tokens": 15800, "completion_tokens": 900, "total_tokens": 16700, "cost_usd": 0.007}


def clip_file_size(clip: Clip) -> int:
    return Path(clip.path).stat().st_size * 10  # generous bound: payload is not bloated


def test_frames_mode_still_available(monkeypatch, tmp_path):
    from statman.autotag import tagger as T

    monkeypatch.setenv("TAGGER_INPUT", "frames")
    t = VisionLLMTagger(api_url="http://x", model="m", frames=2)
    assert t.input_mode == "frames"
    monkeypatch.setattr(T, "extract_frames", lambda *a, **k: [(1.0, b"j"), (2.0, b"j")])
    monkeypatch.setattr(t, "_post", lambda body: (seen.append(body), chat([]))[1])
    seen: list = []
    t.tag_clip(Clip(0, 0, 60, 0, 1, str(tmp_path / "c.mp4")), {})
    assert [p["type"] for p in seen[0]["messages"][1]["content"]].count("image_url") == 2


# --- schema parsing --------------------------------------------------------

def test_clock_parsing():
    assert clock_to_seconds("37:12") == 2232 and clock_to_seconds("45+2:10") == 2830
    assert clock_to_seconds(None) is None and clock_to_seconds("x") is None
    clip = Clip(3, 165, 225, 2865, 2)
    assert clock_to_clip_seconds("48:00", clip) == 15.0
    assert clock_to_clip_seconds("00:20", clip) == 20.0  # clip-relative time fallback
    assert clock_to_clip_seconds("99:00", clip) == 60.0


def test_parse_code_events_with_end_points_and_outcomes():
    t = VisionLLMTagger(api_url="x", model="m")
    clip = Clip(1, 55, 115, 55, 1)
    payload = chat([
        code_ev("01:00", "home", "PASS", "success", 30, 40, 45, 20),
        code_ev("01:02", "home", "CROSS", "fail", 85, 5, 95, 50),
        code_ev("01:03", "away", "RECOVERY", None, 3, 50, 3, 50, detail="GK catches cross"),
        code_ev("01:10", "home", "SHOT", "blocked", 82, 45, 85, 48),
        code_ev("01:20", "away", "SHOT", "goal", 90, 50, 100, 50),
        code_ev("01:30", "home", "GAP", None, None, None, detail="replay"),
        code_ev("01:31", "away", "GK_PASS", "success", 5, 50, 60, 10),
        code_ev("01:40", "home", "CARD", "yellow"),
        {"clock": "01:41", "team": "home", "code": "NOPE", "confidence": 1},
    ])
    out = t.parse_response(payload, clip)
    assert [e["code"] for e in out] == ["PASS", "CROSS", "RECOVERY", "SHOT", "SHOT", "GAP", "GK_PASS", "CARD"]
    p, c, r, s1, s2, gap, gk, card = out
    assert p["attributes"] == {"completed": True} and (p["x2"], p["y2"]) == (45, 20) and p["t_clip_seconds"] == 5.0
    assert c["type"] == "pass" and c["attributes"] == {"completed": False, "cross": True}
    assert r["type"] == "recovery" and r["team"] == "away"
    assert s1["attributes"]["outcome"] == "blocked" and s2["attributes"]["outcome"] == "goal"
    assert gap["type"] == "gap" and gap["x"] is None
    assert gk["attributes"] == {"completed": True, "length": "long", "lane": "flank"}
    assert card["attributes"] == {"color": "yellow"}

    events = build_timeline([(clip, out)], threshold=0.5)
    pas = next(e for e in events if e["code"] == "PASS")
    assert (pas["x"], pas["y"], pas["x2"], pas["y2"], pas["outcome"]) == (30, 40, 45, 20, "success")
    assert pas["t_match_seconds"] == 60.0 and pas["review_status"] == "auto"
    shot = next(e for e in events if e["code"] == "SHOT" and e["team"] == "home")
    assert shot["attributes"]["on_target"] is False


def test_code_conversion_rules():
    assert from_code_event({"code": "INTERCEPT", "team": "home"})["type"] == "interception"
    assert from_code_event({"code": "AERIAL", "outcome": "fail"})["attributes"] == {"won": False}
    assert from_code_event({"code": "LOST", "detail": "heavy touch"})["attributes"] == {"reason": "miscontrol"}
    assert from_code_event({"code": "throw_in", "outcome": "success"})["type"] == "throw_in"
    assert from_code_event({"code": "WHATEVER"}) is None
    schema = code_json_schema()["properties"]["events"]["items"]
    assert {"x1", "y1", "x2", "y2", "outcome", "clock", "code"} <= set(schema["required"])


# --- overlap dedupe --------------------------------------------------------

def test_overlap_dedupe_same_team_code_clock_and_place():
    a, b = Clip(0, 0, 60, 0, 1), Clip(1, 55, 115, 55, 1)
    raw_a = [
        code_ev("00:57", "home", "PASS", "success", 40, 40, 55, 30, conf=0.7),
        code_ev("00:58", "away", "TACKLE", "success", 30, 60),
    ]
    raw_b = [
        {**code_ev("00:58", "home", "PASS", "success", 42, 41, None, None, conf=0.9), "shirt": 8},
        code_ev("00:58", "home", "PASS", "success", 80, 90, 85, 95),   # far away: a different pass
        code_ev("00:57", "home", "CROSS", "success", 41, 40, 90, 50),  # other code: kept
        code_ev("00:58", "away", "TACKLE", "success", 31, 61),         # duplicate tackle
    ]
    ta = VisionLLMTagger(api_url="x", model="m")
    events = build_timeline([(a, ta.parse_response(chat(raw_a), a)), (b, ta.parse_response(chat(raw_b), b))])
    passes = [e for e in events if e["code"] == "PASS"]
    assert len(passes) == 2
    merged = next(p for p in passes if p["x"] < 50)
    assert merged["clip_ids"] == [0, 1] and merged["shirt"] == 8 and (merged["x2"], merged["y2"]) == (55, 30)
    assert sum(1 for e in events if e["code"] == "CROSS") == 1
    assert sum(1 for e in events if e["code"] == "TACKLE") == 1


# --- job: context, usage, storage, stats -----------------------------------

class FakeVideoTagger:
    name = "fake_video"

    def __init__(self):
        self.contexts = []
        self.last_usage = {}

    def enabled(self):
        return True

    def tag_clip(self, clip, context):
        self.contexts.append(context)
        self.last_usage = {"prompt_tokens": 16000, "completion_tokens": 1000, "total_tokens": 17000, "cost_usd": 0.0073}
        base = clip.match_start
        mm = lambda s: f"{int(s // 60):02d}:{int(s % 60):02d}"  # noqa: E731
        return [
            {**code_ev(mm(base + 2), "home", "PASS", "fail", 40, 50, 70, 20), "t_clip_seconds": 2},
            {**code_ev(mm(base + 4), "away", "SHOT", "on", 85, 50, 100, 45, shirt=9), "t_clip_seconds": 4},
        ]


def _code_raw(events, clip):
    return VisionLLMTagger(api_url="x", model="m").parse_response(chat(events), clip)


def test_job_context_usage_storage_and_stats(video_70s):
    from fastapi.testclient import TestClient

    from statman.api import app

    jobs.save_settings("vid1", {"home_name": "Napoli", "away_name": "Bari", "home_kit": "blue",
                                "home_attacks_first_half": "right"})
    store.write_doc("vid1", "lineup", {"players": [{"team": "away", "shirt": 9, "name": "Moncini"}]})
    jobs.create_job("vid1", video_70s, segments=[{"video_start": 0, "match_start": 0},
                                                  {"video_start": 55, "match_start": 2700}])
    fake = FakeVideoTagger()

    class Wrapper(FakeVideoTagger):
        def tag_clip(self, clip, context):
            fake.contexts.append(context)
            self.last_usage = dict(FakeVideoTagger.tag_clip(fake, clip, context) and fake.last_usage)
            return _code_raw([{k: v for k, v in e.items() if k != "t_clip_seconds"}
                              for e in FakeVideoTagger.tag_clip(fake, clip, context)], clip)

    meta = jobs.process_job("vid1", tagger=Wrapper())
    assert meta["status"] == "done", meta.get("error")
    ctx1, ctx2 = fake.contexts[0], fake.contexts[-1]
    assert ctx1["teams"] == {"home": "Napoli", "away": "Bari"} and ctx1["kits"] == {"home": "blue"}
    assert ctx1["home_attacks"] == "right" and ctx2["home_attacks"] == "left"  # second half flips
    assert ctx1["lineups"]["away"] == [{"shirt": 9, "name": "Moncini"}]
    assert "RIGHT" in clip_context_text(Clip(0, 0, 60, 0, 1), ctx1)
    assert meta["usage"]["calls"] == 2 and meta["usage"]["prompt_tokens"] == 32000
    assert meta["usage"]["cost_usd"] == pytest.approx(0.0146) and meta["usage"]["cost_per_clip_usd"] == pytest.approx(0.0073)
    assert [u["clip"] for u in meta["clip_usage"]] == [0, 1]

    events = FileEventRepo().list_events("vid1")
    p = next(e for e in events if e["type"] == "pass")
    assert (p["x2"], p["y2"], p["outcome"], p["code"]) == (70, 20, "fail", "PASS")
    assert p["attributes"]["completed"] is False

    with TestClient(app) as client:
        assert client.get("/api/autotag/matches/vid1").json()["usage"]["calls"] == 2
        stats = client.get("/api/autotag/matches/vid1/stats").json()
        assert stats["teams"]["away"]["shots"] == 2
        assert client.get("/api/autotag/matches/vid1/stats/team.csv").status_code == 200
        players = client.get("/api/autotag/matches/vid1/stats/players.csv")
        assert players.status_code == 200 and "Moncini" in players.text
        assert client.get("/api/autotag/matches/vid1/settings").json()["home_attacks_first_half"] == "right"
        assert client.put("/api/autotag/matches/vid1/settings", json={"home_attacks_first_half": "up"}).status_code == 400
        status = client.get("/api/autotag/tagger").json()["vision_llm"]
        assert status["input"] == "video" and "api_key" not in status
    assert team_csv(match_stats(events)) and player_csv(match_stats(events))
