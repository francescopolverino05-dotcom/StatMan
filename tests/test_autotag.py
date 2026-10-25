"""Phase 2 auto-tagging: clips, tagger, dedupe, review routing, corrections, stats.

All events here are synthetic TEST DATA built inline or from
tests/fixtures/autotag_test_clips.json.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from statman.autotag import jobs, store
from statman.autotag.clips import Clip, cut_clip, plan_clips, video_to_match
from statman.autotag.merge import build_timeline, dedupe_events, clip_events_to_match, review_threshold, route_for_review
from statman.autotag.repo import FileEventRepo
from statman.autotag.review import add_human_event, apply_review, review_queue
from statman.autotag.stats import match_stats, player_csv, player_stats, team_csv, team_stats
from statman.autotag.tagger import FixtureTagger, VisionLLMTagger, get_tagger
from statman.autotag.taxonomy import json_schema, normalize_event

FIXTURE = Path(__file__).parent / "fixtures" / "autotag_test_clips.json"


@pytest.fixture(autouse=True)
def legacy_tagger_defaults(monkeypatch):
    """These tests were written for 15 s clips and the frames tagger; the new
    defaults (60 s, video input) are covered in test_autotag_video.py."""
    monkeypatch.setenv("STATMAN_CLIP_SECONDS", "15")
    monkeypatch.setenv("STATMAN_CLIP_OVERLAP", "5")
    monkeypatch.setenv("TAGGER_INPUT", "frames")
    monkeypatch.delenv("TAGGER_PROMPT", raising=False)


@pytest.fixture
def autotag_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STATMAN_VIDEO_DIR", raising=False)
    monkeypatch.delenv("STATMAN_REVIEW_THRESHOLD", raising=False)
    return tmp_path


@pytest.fixture(scope="module")
def video_25s(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("atv") / "synthetic_25s.mp4"
    subprocess.check_call(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", "25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out


def ev(etype, team, t, conf=0.9, shirt=None, x=None, status="auto", **attrs):
    return {"id": None, "type": etype, "team": team, "shirt": shirt, "player": None, "t_match_seconds": t,
            "x": x, "y": None, "attributes": attrs, "confidence": conf, "review_status": status}


# --- clip planning ---------------------------------------------------------

def test_plan_clips_overlap_and_coverage():
    clips = plan_clips(40, clip_seconds=15, overlap_seconds=5)
    assert [(c.video_start, c.video_end) for c in clips] == [(0, 15), (10, 25), (20, 35), (30, 40)]
    for a, b in zip(clips, clips[1:]):
        assert a.video_end - b.video_start == pytest.approx(5)
    assert clips[-1].video_end == 40


def test_plan_clips_short_and_invalid():
    assert [(c.video_start, c.video_end) for c in plan_clips(9)] == [(0, 9)]
    assert plan_clips(0) == []
    with pytest.raises(ValueError):
        plan_clips(100, clip_seconds=10, overlap_seconds=10)


def test_plan_clips_match_clock_segments():
    segs = [{"video_start": 30, "match_start": 0}, {"video_start": 3100, "match_start": 2700}]
    assert video_to_match(30, segs) == (0.0, 2)  # leading pre-kickoff segment is period 1
    clips = plan_clips(3200, segments=segs)
    c = next(c for c in clips if c.video_start == 3110)
    assert c.match_start == pytest.approx(2710)
    assert next(c for c in clips if c.video_start == 1000).match_start == pytest.approx(970)


def test_cut_clip_ffmpeg(video_25s, tmp_path):
    clip = plan_clips(25)[1]
    out = cut_clip(video_25s, clip, tmp_path)
    assert Path(out.path).stat().st_size > 0
    from statman.video.probe import probe_video
    assert probe_video(Path(out.path))["duration_sec"] == pytest.approx(clip.duration, abs=0.5)


# --- taxonomy --------------------------------------------------------------

def test_taxonomy_rules():
    shot, issues = normalize_event({"type": "shot", "team": "home", "t_match_seconds": 1, "confidence": 0.9,
                                    "attributes": {"outcome": "blocked", "on_target": True}})
    assert shot["attributes"]["on_target"] is False and not issues
    fk, issues = normalize_event({"type": "free_kick", "team": "away", "t_match_seconds": 1, "confidence": 1,
                                  "attributes": {"distance_m": 35, "outcome": "direct_shot"}})
    assert fk is None
    lost, issues = normalize_event({"type": "ball_lost", "team": "away", "t_match_seconds": 1, "confidence": 1,
                                    "attributes": {"reason": "bad_pass"}})
    assert "invalid reason='bad_pass'" in issues and "missing reason" in issues
    assert normalize_event({"type": "dribble", "t_match_seconds": 1})[0] is None
    assert set(json_schema()["properties"]["events"]["items"]["properties"]["type"]["enum"]) >= {"gk_pass", "aerial_duel"}


# --- dedupe / threshold ----------------------------------------------------

def test_dedupe_merges_overlap_duplicates_only():
    c0, c1 = Clip(0, 0, 15, 0, 1), Clip(1, 10, 25, 10, 1)
    a = clip_events_to_match(c0, [
        {"type": "pass", "team": "home", "shirt": 8, "t_clip_seconds": 12.0, "attributes": {"completed": True}, "confidence": 0.7},
        {"type": "pass", "team": "home", "shirt": 6, "t_clip_seconds": 12.5, "attributes": {"completed": True}, "confidence": 0.8},
    ])
    b = clip_events_to_match(c1, [
        {"type": "pass", "team": "home", "shirt": 8, "t_clip_seconds": 2.4, "attributes": {"completed": True, "cross": True}, "confidence": 0.9},
        {"type": "pass", "team": "away", "shirt": 8, "t_clip_seconds": 2.4, "attributes": {"completed": True}, "confidence": 0.9},
    ])
    merged = dedupe_events(a + b)
    assert len(merged) == 3  # home #8 merged; home #6 (same clip, other player) and away kept
    home8 = next(e for e in merged if e["team"] == "home" and e["shirt"] == 8)
    assert home8["confidence"] == 0.9 and home8["clip_ids"] == [0, 1]
    assert home8["attributes"] == {"completed": True, "cross": True}


def test_dedupe_keeps_two_actions_in_same_clip():
    c0 = Clip(0, 0, 15, 0, 1)
    evs = clip_events_to_match(c0, [
        {"type": "pass", "team": "home", "t_clip_seconds": 3.0, "attributes": {"completed": True}, "confidence": 0.9},
        {"type": "pass", "team": "home", "t_clip_seconds": 4.0, "attributes": {"completed": True}, "confidence": 0.9},
    ])
    assert len(dedupe_events(evs)) == 2


def test_threshold_routing(monkeypatch):
    assert review_threshold() == 0.75 or os.environ.get("STATMAN_REVIEW_THRESHOLD")
    monkeypatch.setenv("STATMAN_REVIEW_THRESHOLD", "0.6")
    assert review_threshold() == 0.6
    monkeypatch.setenv("STATMAN_REVIEW_THRESHOLD", "junk")
    assert review_threshold() == 0.75
    evs = [
        {**ev("pass", "home", 1, conf=0.74), "issues": []},
        {**ev("pass", "home", 2, conf=0.75), "issues": []},
        {**ev("pass", "home", 3, conf=0.99), "issues": ["missing completed"]},
    ]
    route_for_review(evs, 0.75)
    assert [e["review_status"] for e in evs] == ["pending", "auto", "pending"]
    assert evs[0]["review_reason"] == ["low confidence"]


def test_build_timeline_from_fixture():
    tagger = FixtureTagger(FIXTURE)
    clips = plan_clips(25)
    events = build_timeline([(c, tagger.tag_clip(c, {})) for c in clips], threshold=0.75)
    shots = [e for e in events if e["type"] == "shot"]
    assert len(shots) == 1 and shots[0]["clip_ids"] == [0, 1]
    assert shots[0]["attributes"]["on_target"] is True
    key = [e for e in events if e["type"] == "pass" and e["attributes"].get("key_pass")]
    assert [e["shirt"] for e in key] == [10]  # last pass before the shot
    assert next(e for e in events if e["type"] == "save")["review_status"] == "pending"


# --- tagger backends -------------------------------------------------------

def test_vision_tagger_disabled_without_env(monkeypatch):
    for k in ("TAGGER_API_URL", "TAGGER_API_KEY", "TAGGER_MODEL", "STATMAN_TAGGER"):
        monkeypatch.delenv(k, raising=False)
    t = get_tagger()
    assert isinstance(t, VisionLLMTagger) and not t.enabled()


def test_vision_tagger_request_and_parse(video_25s, tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        content = json.dumps({"events": [{"type": "corner", "team": "away", "shirt": None, "t_clip_seconds": 4.0,
                                          "x": None, "y": None, "attributes": {}, "confidence": 0.8}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    t = VisionLLMTagger(api_url="http://tagger.test/v1", api_key="k", model="m", frames=3, client=client)
    clip = cut_clip(video_25s, plan_clips(25)[0], tmp_path)
    out = t.tag_clip(clip, {"teams": {"home": "blue", "away": "red"}})
    assert out[0]["type"] == "corner"
    assert seen["url"] == "http://tagger.test/v1/chat/completions" and seen["auth"] == "Bearer k"
    body = seen["body"]
    assert body["response_format"]["json_schema"]["strict"] is True
    images = [p for p in body["messages"][1]["content"] if p["type"] == "image_url"]
    assert len(images) == 3 and images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_vision_tagger_parses_fenced_json():
    t = VisionLLMTagger(api_url="x", model="m")
    payload = {"choices": [{"message": {"content": "```json\n{\"events\": [{\"type\": \"foul\"}, {\"type\": \"nope\"}]}\n```"}}]}
    assert [e["type"] for e in t.parse_response(payload, Clip(0, 0, 15, 0, 1))] == ["foul"]


# --- job + corrections -----------------------------------------------------

def test_job_end_to_end_and_corrections(autotag_root, video_25s):
    jobs.create_job("m1", video_25s)
    meta = jobs.process_job("m1", tagger=FixtureTagger(FIXTURE))
    assert meta["status"] == "done" and meta["clips_total"] == 2
    clips = store.read_doc("m1", "clips")
    assert all(Path(c["path"]).exists() for c in clips)

    repo = FileEventRepo()
    events = repo.list_events("m1")
    queue = review_queue("m1", repo)
    assert queue and all(e["review_status"] == "pending" for e in queue)
    save = next(e for e in events if e["type"] == "save")

    res = apply_review("m1", save["id"], "accept", reviewer="analyst", repo=repo)
    assert res["event"]["review_status"] == "confirmed"
    lost = next(e for e in events if e["type"] == "ball_lost")
    res = apply_review("m1", lost["id"], "edit", changes={"shirt": 5, "attributes": {"reason": "dispossessed"}}, repo=repo)
    assert res["event"]["shirt"] == 5 and res["event"]["attributes"] == {"reason": "dispossessed"}
    assert res["correction"]["before"]["shirt"] == 4 and res["correction"]["after"]["shirt"] == 5
    with pytest.raises(ValueError):
        apply_review("m1", lost["id"], "edit", changes={"attributes": {"reason": "bad"}}, repo=repo)
    p1 = next(e for e in events if e["type"] == "pass" and e["shirt"] == 8)
    apply_review("m1", p1["id"], "delete", repo=repo)
    add_human_event("m1", {"type": "corner", "team": "home", "t_match_seconds": 20}, repo=repo)

    corrections = repo.list_corrections("m1")
    assert [c["action"] for c in corrections] == ["accept", "edit", "delete", "add"]
    stats = match_stats(repo.list_events("m1"))
    assert stats["teams"]["home"]["passes"] == 1  # deleted pass excluded
    assert stats["teams"]["home"]["corners"] == 1

    # Re-tagging keeps reviewed events and replaces only unreviewed AI rows.
    jobs.create_job("m1", video_25s)
    jobs.process_job("m1", tagger=FixtureTagger(FIXTURE))
    after = repo.list_events("m1")
    assert any(e["review_status"] == "corrected" and e["shirt"] == 5 for e in after)
    # The corrected ball_lost stays; the re-tagged AI copy of it lands as a separate pending/auto row.
    assert sum(1 for e in after if e["type"] == "ball_lost" and e["review_status"] == "corrected") == 1
    assert not any(e["review_status"] == "rejected" and e["type"] != "pass" for e in after)


def test_job_tagger_disabled(autotag_root, video_25s):
    jobs.create_job("m2", video_25s)
    meta = jobs.process_job("m2", tagger=VisionLLMTagger(api_url="", model=""))
    assert meta["status"] == "tagger_disabled"
    assert len(store.read_doc("m2", "clips")) == 2


# --- stats maths -----------------------------------------------------------

def _sample_events():
    return [
        # home passes: 3 attempted (2 own half, 1 opp half), 2 completed
        ev("pass", "home", 10, shirt=4, x=20, completed=True),
        ev("pass", "home", 20, shirt=4, x=40, completed=False),
        ev("pass", "home", 30, shirt=8, x=70, completed=True, key_pass=True, progressive=True, line_broken="defence"),
        ev("gk_pass", "home", 40, shirt=1, x=5, length="long", lane="flank", completed=False),
        # away passes: 4 in own half (x<50), 1 in opp half, all completed
        *[ev("pass", "away", 50 + i, shirt=6, x=10 + i * 5, completed=True) for i in range(4)],
        ev("pass", "away", 60, shirt=6, x=80, completed=True, cross=True),
        # home defensive actions in away half (x>=50): tackle + foul; interception in own half
        ev("tackle", "home", 70, shirt=4, x=60, won=True),
        ev("foul", "home", 75, shirt=4, x=55),
        ev("interception", "home", 80, shirt=4, x=30),
        ev("interception", "home", 81, shirt=4),  # no x -> excluded from ppda
        # shots
        ev("shot", "home", 90, shirt=8, xg=0.4, on_target=True, inside_box=True, outcome="goal"),
        ev("goal", "home", 90, shirt=8),
        ev("shot", "home", 100, shirt=9, xg=0.05, on_target=False, inside_box=False, outcome="blocked"),
        ev("shot", "away", 110, shirt=9, on_target=True, outcome="saved"),
        ev("save", "home", 110, shirt=1),
        ev("card", "away", 120, shirt=6, color="yellow"),
        ev("aerial_duel", "home", 130, shirt=4, won=True, source="long_ball"),
        ev("aerial_duel", "away", 130, shirt=9, won=False, source="long_ball"),
        ev("free_kick", "home", 140, shirt=8, distance_m=22, outcome="direct_shot"),
        ev("pass", "home", 150, shirt=4, x=30, completed=True, status="rejected"),
        ev("pass", "home", 160, shirt=4, x=30, completed=True, status="pending"),
    ]


def test_team_stats_maths():
    s = team_stats(_sample_events())
    h, a = s["home"], s["away"]
    # passes = PASS + GK_PASS + FK + GOALKICK + THROW (build3.py); crosses and direct-shot FKs are not passes
    assert h["passes"] == 5 and h["passes_completed"] == 3 and h["pass_accuracy_pct"] == 60.0
    assert a["passes"] == 4 and a["crosses"] == 1
    # possession: share of passes attempted, 5 of 9
    assert h["possession_pct"] == 55.6 and a["possession_pct"] == 44.4
    # PPDA home: away passes in own half 4 / home (tackle+foul) in away half 2 = 2.0
    assert h["ppda"] == 2.0 and h["ppda_events_without_x"] == 1
    # PPDA away: home PASS/CROSS at x<=60 (20, 40, 30 pending; gk_pass is not counted) = 3 / 0 actions -> None
    assert a["ppda"] is None and a["ppda_opponent_passes"] == 3
    assert h["goals"] == 1 and a["goals_conceded"] == 1 and h["goals_conceded"] == 0
    assert h["shots"] == 2 and h["shots_on_target"] == 1 and h["shots_off_target"] == 1
    assert h["shot_accuracy_pct"] == 50.0 and h["xg"] == 0.45
    assert h["shots_inside_box"] == 1 and h["shots_outside_box"] == 1
    assert h["key_passes"] == 1 and h["progressive_passes"] == 0 and h["progressive_candidates_without_coords"] == 5 and h["line_broken"] == {"defence": 1}
    assert a["crosses"] == 1 and a["yellow_cards"] == 1
    assert h["gk_saves"] == 1 and h["save_pct"] == 100.0 and h["shots_faced"] == 1 and h["on_target_faced"] == 1
    assert a["save_pct"] == 0.0 and a["xg_missing"] == 1
    assert h["aerials_won"] == 1 and a["aerials_lost"] == 1
    assert h["free_kicks_30m"] == 1 and h["free_kicks_30m_direct_shot"] == 1
    assert h["gk_passes_long"] == 1 and h["gk_passes_flank"] == 1 and h["gk_pass_accuracy_pct"] == 0.0
    confirmed = team_stats(_sample_events(), confirmed_only=True)
    assert confirmed["home"]["passes"] == 4  # pending pass left out


def test_player_stats_and_minutes():
    lineup = {"match_minutes": 94, "players": [
        {"team": "home", "shirt": 1, "name": "Test GK", "position": "GK", "starter": True},
        {"team": "home", "shirt": 4, "name": "Test Four", "starter": True, "off_minute": 60},
        {"team": "home", "shirt": 14, "name": "Test Sub", "starter": False, "on_minute": 60},
        {"team": "home", "shirt": 15, "name": "Unused", "starter": False},
    ]}
    rows = {(r["team"], r["shirt"]): r for r in player_stats(_sample_events(), lineup)}
    gk = rows[("home", 1)]
    assert gk["role"] == "goalkeeper" and gk["minutes"] == 94 and gk["saves"] == 1 and gk["conceded"] == 0
    assert gk["passes_long"] == 1 and gk["passes_long_accuracy_pct"] == 0.0
    four = rows[("home", 4)]
    assert four["minutes"] == 60 and four["passes"] == 3 and four["pass_accuracy_pct"] == pytest.approx(66.7)
    assert four["tackles"] == 1 and four["interceptions"] == 2 and four["aerials_won"] == 1
    assert rows[("home", 14)]["minutes"] == 34 and rows[("home", 15)]["minutes"] is None
    eight = rows[("home", 8)]
    assert eight["goals"] == 1 and eight["xg"] == 0.4 and eight["key_passes"] == 1 and eight["minutes"] is None
    # away GK inferred without lineup? no save events for away -> outfield rows only
    assert rows[("away", 9)]["shots_on_target"] == 1


def test_csv_exports():
    stats = match_stats(_sample_events())
    team = team_csv(stats).splitlines()
    assert team[0] == "metric,home,away,status,reason" and any(l.startswith("ppda,2.0,") for l in team)
    players = player_csv(stats).splitlines()
    assert players[0].startswith("team,shirt,name,position,minutes")
    assert len(players) == 1 + len(stats["players"])


# --- API -------------------------------------------------------------------

def test_api_review_flow(autotag_root):
    from fastapi.testclient import TestClient

    from statman.api import app

    repo = FileEventRepo()
    store.write_doc("m3", "job", {"match_id": "m3", "status": "done"})
    timeline = build_timeline([(Clip(0, 0, 15, 0, 1), json.loads(FIXTURE.read_text())["clips"]["0"])], threshold=0.85)
    repo.replace_ai_events("m3", timeline)
    with TestClient(app) as client:
        assert client.get("/review").status_code == 200
        assert "review_threshold" in client.get("/api/autotag/tagger").json()
        q = client.get("/api/autotag/matches/m3/review-queue").json()
        assert q["count"] == 1  # only the 0.8 pass is below 0.85; the 0.85 shot is at threshold
        eid = q["events"][0]["id"]
        r = client.post(f"/api/autotag/matches/m3/events/{eid}/review", json={"action": "edit", "changes": {"team": "away"}})
        assert r.status_code == 200 and r.json()["event"]["review_status"] == "corrected"
        assert client.post(f"/api/autotag/matches/m3/events/{eid}/review", json={"action": "nope"}).status_code == 400
        assert client.get("/api/autotag/matches/m3/corrections").json()["count"] == 1
        assert client.put("/api/autotag/matches/m3/lineup", json={"players": [{"team": "home", "shirt": 8}]}).status_code == 200
        stats = client.get("/api/autotag/matches/m3/stats").json()
        assert stats["teams"]["home"]["shots"] == 1
        csv = client.get("/api/autotag/matches/m3/stats/players.csv")
        assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
        assert client.get("/api/autotag/matches/..%2Fx/events").status_code in (400, 404)
        assert client.post("/api/autotag/matches/nope/run", json={}).status_code == 404


def test_video_page_has_run_autotag_button(autotag_root):
    from fastapi.testclient import TestClient

    from statman.api import app

    with TestClient(app) as client:
        page = client.get("/video")
        assert page.status_code == 200
        assert 'id="autotag-btn"' in page.text and "Run auto-tag" in page.text
        js = client.get("/static/video.js")
        assert js.status_code == 200
        assert "/run" in js.text and "video_job_id" in js.text and "/review?match=" in js.text
        # run endpoint the button posts to: unknown video job -> 404, bad id -> 400/404
        assert client.post("/api/autotag/matches/nojob1/run", json={"video_job_id": "nojob1"}).status_code == 404
        assert client.get("/api/autotag/matches/nojob1").status_code == 404


# --- Postgres repository (runs when STATMAN_TEST_DATABASE_URL is set) -------

PG_URL = os.environ.get("STATMAN_TEST_DATABASE_URL", "").strip()


@pytest.mark.skipif(not PG_URL, reason="STATMAN_TEST_DATABASE_URL not set")
def test_postgres_repo_events_and_corrections(autotag_root, monkeypatch):
    import psycopg

    from statman.persistence import backend as backend_mod
    from statman.autotag.repo import PostgresEventRepo

    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    backend_mod.reset_backend()
    try:
        repo = PostgresEventRepo(PG_URL)
        timeline = build_timeline([(Clip(0, 0, 15, 0, 1), json.loads(FIXTURE.read_text())["clips"]["0"])], threshold=0.85)
        saved = repo.replace_ai_events("pg1", timeline)
        assert len(saved) == 3
        pending = review_queue("pg1", repo)
        assert len(pending) == 1
        res = apply_review("pg1", pending[0]["id"], "edit", changes={"shirt": 11}, reviewer="t", repo=repo)
        assert res["event"]["shirt"] == 11 and res["event"]["review_status"] == "corrected"
        shot = next(e for e in saved if e["type"] == "shot")
        apply_review("pg1", shot["id"], "delete", repo=repo)
        with psycopg.connect(PG_URL) as conn:
            assert conn.execute("SELECT count(*) FROM event_review_queue WHERE match_id='pg1'").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM corrections WHERE match_id='pg1'").fetchone()[0] == 2
            assert conn.execute("SELECT review_status FROM events WHERE id=%s", (shot["id"],)).fetchone()[0] == "rejected"
        assert [c["action"] for c in repo.list_corrections("pg1")] == ["edit", "delete"]
        repo.replace_ai_events("pg1", timeline)  # re-tag keeps reviewed rows
        rows = repo.list_events("pg1")
        assert sum(1 for e in rows if e["review_status"] in {"corrected", "rejected"}) == 2
        assert match_stats(rows)["teams"]["home"]["shots"] == 1
    finally:
        backend_mod.reset_backend()


def test_tuning_normalize_collapse_and_repetition():
    from statman.autotag import tagger as T

    assert T.normalize_event({"event_type": "Free Kick", "t": 2})["type"] == "free_kick"
    assert T.VisionLLMTagger.is_collapsed({"usage": {"completion_tokens": 5}})
    assert not T.VisionLLMTagger.is_collapsed({"usage": {"completion_tokens": 400}})
    ft = [0.75 + 1.5 * i for i in range(10)]
    ev = [{"type": "shot", "team": "home", "t_clip_seconds": t} for t in ft]
    ev += [{"type": "pass", "team": "home", "t_clip_seconds": t, "confidence": 0.9} for t in ft]
    out = T.suppress_repetition(ev, ft)
    shots = [e for e in out if e["type"] == "shot"]
    assert len(shots) == 5  # one per >=2 s window
    assert all(e.get("suspect") == "one_per_frame" and e["confidence"] <= 0.2 for e in out if e["type"] == "pass")


def test_tuning_collapse_retries_with_json_object(tmp_path, monkeypatch):
    from statman.autotag import tagger as T
    from statman.autotag.clips import Clip

    calls = []
    payloads = [
        {"choices": [{"message": {"content": '{"events": []}'}}], "usage": {"completion_tokens": 5, "cost": 0.001}},
        {"choices": [{"message": {"content": '{"events": [{"event_type": "corner", "team": "home", "t_clip_seconds": 4}]}'}}],
         "usage": {"completion_tokens": 80, "cost": 0.002}},
    ]
    tg = T.VisionLLMTagger(api_url="http://x", model="m", frames=3, response_format="json_schema")
    monkeypatch.setattr(T, "extract_frames", lambda *a, **k: [(0.5, b"j"), (5.0, b"j"), (10.0, b"j")])
    monkeypatch.setattr(tg, "_post", lambda body: (calls.append(body.get("response_format", {}).get("type")), payloads[len(calls) - 1])[1])
    clip = Clip.from_dict({"index": 0, "video_start": 0, "video_end": 15, "match_start": 0, "half": 1, "path": str(tmp_path / "c.mp4")})
    out = tg.tag_clip(clip, {"home_attacks": "right"})
    assert calls == ["json_schema", "json_object"]
    assert [e["type"] for e in out] == ["corner"]
    assert abs(tg.total_cost - 0.003) < 1e-9
