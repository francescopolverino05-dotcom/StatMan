"""Accuracy fixes for the auto-tagger. Offline only: mocked model output, no HTTP, no paid calls."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from statman.autotag import jobs, quality, store
from statman.autotag.clips import Clip, encode_for_model
from statman.autotag.stats import match_stats
from statman.autotag.tagger import (
    FixtureTagger, VisionLLMTagger, clip_context_text, has_lineup, on_pitch_players, parse_relook,
)
from statman.autotag.taxonomy import zone_to_xy

FIX = Path(__file__).parent / "fixtures"
CLIP = Clip(0, 0, 60, 960, 1)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in list(quality.DEFAULTS) + ["TAGGER_PROMPT", "TAGGER_VIDEO_FPS", "TAGGER_VIDEO_STRETCH", "TAGGER_INPUT",
                                       "STATMAN_AT_EXTRA_MIN_CONF", "STATMAN_AT_COORD_MIN_CONF", "STATMAN_JOB_MAX_COST",
                                       "STATMAN_GOAL_RELOOK", "TAGGER_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")


def tagger(**kw):
    return VisionLLMTagger(api_url="http://x", model="google/gemini-2.5-flash", **kw)


def chat(obj):
    return {"choices": [{"message": {"content": json.dumps(obj)}}]}


LINEUP = {"players": [
    {"team": "home", "shirt": 9, "name": "Lukaku", "starter": True, "on_minute": None, "off_minute": 70},
    {"team": "home", "shirt": 21, "name": "Politano", "starter": True, "on_minute": None, "off_minute": None},
    {"team": "home", "shirt": 11, "name": "Sub Striker", "starter": False, "on_minute": 70, "off_minute": None},
    {"team": "home", "shirt": 30, "name": "Unused", "starter": False, "on_minute": None, "off_minute": None},
    {"team": "away", "shirt": 1, "name": "Keeper", "starter": True, "on_minute": None, "off_minute": None},
], "source": "match_sheet"}


# --- 6. cadence quality check ----------------------------------------------

def test_fabricated_one_per_second_output_fails_cadence():
    events = json.loads((FIX / "ai_fixed_cadence_clip.json").read_text())
    q = quality.check_clip(events, 60)
    codes = {i["code"] for i in q["hard"]}
    assert not q["passed"]
    assert {"fixed_cadence", "even_spacing"} <= codes, codes
    assert q["stats"]["rate"] > 0.75


def test_real_hand_tag_density_does_not_trip_cadence():
    # ~38 events in 60 s, gaps of 1-2 s on whole seconds: the densest real Napoli-Spezia minute.
    gaps = [2, 1, 2, 1, 2, 2, 1, 2, 1, 1, 2, 2, 1, 2, 1, 2, 1, 1, 2, 2, 1, 2, 1, 2, 2, 1, 1, 2, 1, 2, 2, 1, 2, 1, 2, 1, 1]
    t, events = 1.0, []
    for i, g in enumerate(gaps + [0]):
        events.append({"type": "pass", "team": "home" if i % 3 else "away", "t_clip_seconds": t,
                       "x": 40, "y": 40, "x2": 55, "y2": 35, "outcome": "fail" if i % 5 == 0 else "success",
                       "shirt": 9, "attributes": {}, "confidence": 0.8})
        t += g
    q = quality.check_clip(events, 60)
    assert not ({"fixed_cadence", "even_spacing"} & {i["code"] for i in q["hard"]}), q["hard"]


def test_no_shirt_numbers_fails_only_when_lineup_given():
    events = json.loads((FIX / "ai_fixed_cadence_clip.json").read_text())
    assert all(e.get("shirt") is None for e in events)
    with_lineup = {i["code"] for i in quality.check_clip(events, 60, lineup_given=True)["hard"]}
    without = {i["code"] for i in quality.check_clip(events, 60)["hard"]}
    assert "no_shirt_numbers" in with_lineup and "no_shirt_numbers" not in without


def test_cadence_failure_triggers_retag_loop(monkeypatch, tmp_path):
    bad = json.loads((FIX / "ai_fixed_cadence_clip.json").read_text())
    good = [{"type": "pass", "team": "home" if i % 3 else "away", "t_clip_seconds": t, "x": 40, "y": 40, "x2": 55, "y2": 35,
             "outcome": "fail" if i < 3 else "success", "shirt": 9, "attributes": {}, "confidence": 0.8}
            for i, t in enumerate([1.4, 3.0, 5.9, 7.2, 10.8, 12.1, 15.5, 18.0, 19.3, 23.7, 26.2, 28.8, 31.0,
                                   33.6, 37.9, 40.2, 43.3, 46.0, 49.4, 52.8, 55.1, 57.7])]

    class T:
        name = "t"
        def __init__(self):
            self.out, self.ctx = [bad, good], []
        def enabled(self):
            return True
        def tag_clip(self, clip, ctx):
            self.ctx.append(ctx)
            return [dict(e) for e in self.out.pop(0)]

    t = T()
    store.write_doc("m1", "job", {"match_id": "m1"})
    monkeypatch.setattr(jobs, "_update", lambda *a, **k: {})
    ev, rec, err = jobs._tag_with_quality("m1", t, Clip(0, 0, 60, 0, 1), {"lineups": {}}, [])
    assert rec["chosen_attempt"] == 1 and rec["passed"], rec["attempts"]
    assert "fixed cadence" in t.ctx[1]["corrective"] or "apart" in t.ctx[1]["corrective"]


# --- 3. lineup injection -----------------------------------------------------

def test_on_pitch_players_respects_sub_minutes():
    first = [p["shirt"] for p in on_pitch_players(LINEUP, "home", 960, 1020)]
    late = [p["shirt"] for p in on_pitch_players(LINEUP, "home", 75 * 60, 76 * 60)]
    assert first == [9, 21] and late == [11, 21]


def test_lineup_injected_into_clip_prompt():
    ctx = {"teams": {"home": "Napoli", "away": "Spezia"}, "kits": {"home": "light blue"}, "lineup_doc": LINEUP,
           "lineups": {"home": [], "away": []}}
    text = clip_context_text(CLIP, ctx, scale=5)
    assert "9 Lukaku" in text and "21 Politano" in text and "Sub Striker" not in text and "Unused" not in text
    assert "light blue" in text and "confirmed match sheet" in text
    assert "5" in text and "slow" in text.lower()
    assert has_lineup(ctx)


def test_core_prompt_demands_shirts_and_forbids_cadence():
    sys_prompt = " ".join(tagger()._system_prompt_text() if hasattr(tagger(), "_system_prompt_text") else [])
    from statman.autotag.tagger import CORE_PROMPT
    p = "\n".join(CORE_PROMPT).lower()
    assert "shirt" in p and "null" in p and ("cadence" in p or "every second" in p or "regular" in p)
    assert sys_prompt is not None


def test_tagger_context_loads_confirmed_lineup_doc():
    store.write_doc("m2", "lineup", LINEUP)
    ctx = jobs.tagger_context("m2", {"teams": {"home": "Napoli", "away": "Spezia"}})
    assert ctx["lineup_doc"]["players"][0]["shirt"] == 9 and has_lineup(ctx)
    assert jobs.tagger_context("m3", {})["lineup_doc"] is None


# --- 4 + 5. event filtering, zones, time scale -------------------------------

def _parse(events, **kw):
    return tagger(**kw).parse_response(chat({"events": events}), CLIP)


def test_extras_dropped_unless_high_confidence_and_time_unscaled():
    out = _parse([
        {"t": 50.0, "team": "home", "code": "PASS", "shirt": 9, "outcome": "success", "zone": "3C", "end_zone": "4L",
         "coord_confidence": 0.9, "detail": None, "confidence": 0.8},
        {"t": 60.0, "team": "away", "code": "CLEAR", "shirt": None, "outcome": None, "zone": "1C", "end_zone": None,
         "coord_confidence": 0.5, "detail": None, "confidence": 0.6},
        {"t": 70.0, "team": "away", "code": "AERIAL", "shirt": 4, "outcome": "success", "zone": "2C", "end_zone": None,
         "coord_confidence": 0.5, "detail": None, "confidence": 0.95},
    ])
    assert [e["type"] for e in out][0] == "pass" and len(out) == 2
    p = out[0]
    assert p["t_clip_seconds"] == pytest.approx(10.0)  # 50 s of 5x slowed video = 10 s real
    assert p["shirt"] == 9
    assert (p["x"], p["y"]) == pytest.approx(zone_to_xy("3C")) and (p["x2"], p["y2"]) == pytest.approx(zone_to_xy("4L"))
    assert p["attributes"]["coords_estimated"] is False and p["attributes"]["coord_confidence"] == 0.9


def test_zone_mapping_centres():
    assert zone_to_xy("1L")[0] < zone_to_xy("6L")[0]
    assert zone_to_xy("4L") == pytest.approx((58.33, 83.33), abs=0.01)
    assert zone_to_xy("9Z") is None and zone_to_xy(None) is None


def test_low_coord_confidence_progressive_pass_is_estimated_not_counted():
    def ev(cc):
        return {"t": 25.0, "team": "home", "code": "PASS", "shirt": 21, "outcome": "success", "zone": "2C",
                "end_zone": "5C", "coord_confidence": cc, "detail": None, "confidence": 0.8}
    hi, lo = _parse([ev(0.9)])[0], _parse([ev(0.3)])[0]
    assert lo["attributes"]["coords_estimated"] is True
    base = {"period": 1, "review_status": "confirmed", "source": "ai", "player": None}
    for e, t in ((hi, 10), (lo, 20)):
        e.update(base, t_match_seconds=t, video_ts_seconds=t)
    s = match_stats([hi, lo])
    home = s["teams"]["home"]
    assert home["progressive_passes"] == 1 and home["progressive_passes_estimated"] == 1
    assert s["stat_flags"]["progressive_passes"]["status"] == "estimated"


def test_default_video_settings_and_stretch_encode(tmp_path):
    t = tagger()
    assert t.prompt == "core" and t.video_fps == 5 and t.video_stretch and t.time_scale == 5
    src = tmp_path / "s.mp4"
    subprocess.check_call(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", "4",
                           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = tmp_path / "o.mp4"
    out.write_bytes(encode_for_model(src, height=180, fps=5, stretch=True))
    info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                               "stream=nb_read_frames:format=duration", "-of", "json", str(out)]))
    assert float(info["format"]["duration"]) == pytest.approx(20, abs=1.5)  # 4 s x 5 = 20 s at 1 fps
    assert int(info["streams"][0]["nb_read_frames"]) == pytest.approx(20, abs=2)  # 20 real frames, one per video s


# --- 7. goal re-look ---------------------------------------------------------

def _goal_inputs():
    sb = {"enabled": True, "goals": [{"team": "home", "video_ts_seconds": 130.0, "score_change_video_s": 130.0,
                                      "t_match_seconds": 1090.0, "period": 1}]}
    events = [{"type": "goal", "team": "home", "shirt": None, "player": None, "t_match_seconds": 1090.0,
               "video_ts_seconds": 130.0, "period": 1, "attributes": {"scorebug_confirmed": True}, "confidence": 0.95},
              {"type": "pass", "team": "home", "t_match_seconds": 1080.0, "video_ts_seconds": 120.0, "attributes": {}}]
    ctx = {"teams": {"home": "Napoli", "away": "Spezia"}, "lineup_doc": LINEUP}
    return sb, events, ctx


def test_goal_relook_fills_scorer_assist_and_anchors_time():
    sb, events, ctx = _goal_inputs()
    t = FixtureTagger({"goals": [{"goal_seen": True, "t": 17.0, "team": "home", "scorer_shirt": 9,
                                  "assist_shirt": 21, "own_goal": False, "headed": True, "confidence": 0.8}]})
    out, rows = jobs.relook_goals("m", t, events, sb, Path("v.mp4"), ctx, [])
    g = out[0]
    assert rows[0]["start"] == 110.0 and rows[0]["duration"] == 25.0
    assert g["shirt"] == 9 and g["player"] == "Lukaku"
    assert g["attributes"]["assist_shirt"] == 21 and g["attributes"]["assist_player"] == "Politano"
    assert g["attributes"]["relook"] and g["attributes"]["headed"]
    assert g["video_ts_seconds"] == 127.0 and g["t_match_seconds"] == 1087.0
    assert match_stats([{**g, "review_status": "confirmed"}])["players"]


def test_goal_relook_out_of_window_time_keeps_scorebug_anchor():
    sb, events, ctx = _goal_inputs()
    t = FixtureTagger({"goals": [{"goal_seen": True, "t": 99.0, "scorer_shirt": 9}]})
    g = jobs.relook_goals("m", t, events, sb, Path("v.mp4"), ctx, [])[0][0]
    assert g["video_ts_seconds"] == 130.0 and g["shirt"] == 9


def test_goal_relook_respects_job_budget(monkeypatch):
    monkeypatch.setenv("STATMAN_JOB_MAX_COST", "0.05")
    sb, events, ctx = _goal_inputs()
    t = FixtureTagger({"goals": [{"goal_seen": True, "t": 17.0, "scorer_shirt": 9}]})
    out, rows = jobs.relook_goals("m", t, events, sb, Path("v.mp4"), ctx, [{"clip": 0, "cost_usd": 0.06}])
    assert out[0]["shirt"] is None and "budget" in rows[0]["skipped"]


def test_goal_relook_http_payload_uses_strict_schema_and_unscales(tmp_path):
    src = tmp_path / "g.mp4"
    subprocess.check_call(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", "30",
                           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={**chat({"goal_seen": True, "t": 85.0, "team": "home", "scorer_shirt": 9,
                                                 "assist_shirt": None, "own_goal": False, "headed": False,
                                                 "detail": None, "confidence": 0.7}),
                                         "usage": {"prompt_tokens": 33000, "completion_tokens": 80, "cost": 0.01}})

    t = VisionLLMTagger(api_url="http://x", api_key="k", model="m", client=httpx.Client(transport=httpx.MockTransport(handler)))
    ans = t.relook_goal(src, 2.0, 25.0, {"teams": {"home": "Napoli"}, "lineup_doc": LINEUP, "goal_team": "Napoli"})
    assert ans["t"] == 17.0 and ans["scorer_shirt"] == 9
    assert seen["body"]["response_format"]["json_schema"]["name"] == "statman_goal"
    assert t.last_usage.get("cost_usd") == 0.01


def test_parse_relook_handles_garbage():
    assert parse_relook({"choices": []}) is None
    assert parse_relook(chat({"goal_seen": False, "t": None}))["goal_seen"] is False
