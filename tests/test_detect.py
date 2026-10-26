"""Unit tests for statman.detect (no YOLO weights, no video files, no network)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from statman.detect import ball, camera, evaluate, extract, moments, teams
from statman.detect.extract import Ball, Frame, Person

BLUE_LAB = (180.0, 120.0, 100.0)
BLACK_LAB = (20.0, 128.0, 128.0)


def _player(x, y, color, role="player", h=40.0):
    return Person((x - 8, y - h, x + 8, y), 0.9, color, role)


def _team_model():
    return teams.TeamModel(np.array(BLUE_LAB), np.array(BLACK_LAB), max_dist=30.0)


def test_kmeans_and_team_fit_maps_hints():
    rng = np.random.default_rng(1)
    cols = [tuple(np.array(BLUE_LAB) + rng.normal(0, 2, 3)) for _ in range(60)]
    cols += [tuple(np.array(BLACK_LAB) + rng.normal(0, 2, 3)) for _ in range(50)]
    cols += [(120.0, 180.0, 160.0)] * 8 + [None] * 3  # referee + missing colours
    tm = teams.TeamModel.fit(cols, home_hint=(225, 170, 90), away_hint=(30, 30, 30))
    assert tm.assign(BLUE_LAB) == teams.HOME
    assert tm.assign(BLACK_LAB) == teams.AWAY
    assert tm.assign(None) == teams.OTHER
    # hints swapped -> mapping swaps
    tm2 = teams.TeamModel.fit(cols, home_hint=(30, 30, 30), away_hint=(225, 170, 90))
    assert tm2.assign(BLUE_LAB) == teams.AWAY


def test_team_fit_needs_data():
    with pytest.raises(ValueError):
        teams.TeamModel.fit([BLUE_LAB, None])


def _pass_frames():
    """Blue player at x=100 has the ball, passes it along y=300 to a black player at x=500."""
    frames = []
    for i in range(24):
        t = i / 8
        if t < 1.0:
            bx = 100.0
        elif t < 2.0:
            bx = 100.0 + 400.0 * (t - 1.0)
        else:
            bx = 500.0
        persons = [_player(100, 300, BLUE_LAB), _player(500, 300, BLACK_LAB), _player(300, 100, None, "referee")]
        balls = [Ball(bx, 295.0, 0.4, 4.0), Ball(900.0, 50.0, 0.05, 4.0)]  # real ball + far-away false positive
        frames.append(Frame(t=t, persons=persons, balls=balls))
    return frames


def test_viterbi_prefers_ball_near_players():
    tr = ball.track_viterbi(_pass_frames())
    assert len(tr) == 24
    assert all(abs(y - 295.0) < 1e-6 for _, y, _ in tr.values())


def test_tracklets_drop_static_artifact():
    frames = [Frame(t=i / 8, balls=[Ball(50.0, 50.0, 0.3, 4.0)]) for i in range(40)]
    assert ball.track(frames) == {}


def test_viterbi_interpolates_short_gaps():
    frames = _pass_frames()
    frames[12].balls = []
    tr = ball.track_viterbi(frames)
    x, y, observed = tr[frames[12].t]
    assert not observed and 100 < x < 500


def test_detect_finds_pass_and_possession_change():
    ms = moments.detect(_pass_frames(), _team_model())
    times = [m.t for m in ms]
    # a candidate where the ball leaves the passer (~1.0 s) and one where it arrives (~2.0 s)
    assert any(abs(t - 1.0) <= 0.25 for t in times)
    assert any(abs(t - 2.0) <= 0.25 for t in times)
    arrive = min(ms, key=lambda m: abs(m.t - 2.0))
    assert arrive.team == teams.AWAY
    assert arrive.possession_change and arrive.possession_team == teams.AWAY
    assert all(m.team != "referee" for m in ms)
    d = arrive.to_dict()
    assert d["ball_xy"] is not None and 0 <= d["ball_norm"][0] <= 100


def test_detect_adds_pan_moments():
    frames = _pass_frames()
    ms = moments.detect(frames, _team_model(), pan=[(0.25, 300.0)])
    assert any("pan" in m.sources and abs(m.t - 0.25) < 1e-6 for m in ms)


def test_detect_skips_non_pitch_frames():
    frames = _pass_frames()
    for f in frames:
        f.green = 0.05
    assert moments.detect(frames, _team_model()) == []


def test_pan_events_onset_and_stop():
    series = [(i / 8, 0.0 if i < 20 or i >= 40 else 300.0, 0.0) for i in range(60)]
    ev = camera.pan_events(series, smooth=3, min_change=60, min_sep=0.8)
    ts = [t for t, _ in ev]
    assert len(ev) == 2
    assert abs(ts[0] - 20 / 8) <= 0.25 and abs(ts[1] - 40 / 8) <= 0.25


def test_pan_series_on_synthetic_video(tmp_path):
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(0)
    world = cv2.GaussianBlur((rng.random((240, 800)) * 255).astype(np.uint8), (5, 5), 0)
    path = str(tmp_path / "pan.avi")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 24, (320, 240))
    for i in range(48):
        x = 2 * i  # camera pans right 2 px/frame = 48 px/s
        vw.write(cv2.cvtColor(world[:, x:x + 320], cv2.COLOR_GRAY2BGR))
    vw.release()
    s = camera.pan_series(path, fps=8, scale=1.0)
    assert len(s) >= 10
    vx = np.median([v[1] for v in s])
    assert 30 < vx < 66, vx


def test_save_load_roundtrip(tmp_path):
    frames = _pass_frames()[:3]
    p = tmp_path / "d.json.gz"
    extract.save(frames, p)
    back = extract.load(p)
    assert len(back) == 3 and back[0].persons[2].role == "referee"
    assert back[1].balls[0].x == pytest.approx(100.0)
    assert back[0].persons[0].color == pytest.approx(BLUE_LAB)


def test_torso_color_ignores_grass():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:] = (40, 160, 40)            # grass
    img[20:50, 40:60] = (10, 10, 10)  # black shirt
    g = extract.grass_mask(img)
    c = extract.torso_color(img, (35, 10, 65, 90), g)
    assert c is not None and c[0] < 40


def test_evaluate_matching_and_chance(tmp_path):
    hand = tmp_path / "hand.txt"
    hand.write_text("16:01|Spezia|PASS|CM|8|success|45,50|25,50||med\n"
                    "16:05|Napoli|TACKLE|LM|11|success|55,85|55,85||med\n"
                    "16:09|Napoli|PASS|LM|11|fail|55,85|70,70||med\n")
    H = evaluate.load_hand(hand)
    assert [h.team for h in H] == ["away", "home", "home"]
    assert evaluate.possession_changes(H) == [965]
    pairs = evaluate.match([961, 965, 969], [960.5, 966.8, 990.0], 1)
    assert pairs == [(0, 0)]
    assert len(evaluate.match([961, 965, 969], [960.5, 966.8, 990.0], 2)) == 2
    ms = [{"t": 1.0, "team": "away", "possession_change": False, "possession_team": "away"},
          {"t": 5.2, "team": "home", "possession_change": True, "possession_team": "home"}]
    r = evaluate.score(H, ms, 960, 960, 970)
    assert r["w1"]["matched"] == 2 and r["w1"]["recall"] == pytest.approx(2 / 3, abs=1e-3)
    assert r["team"]["accuracy"] == 1.0
    assert r["possession"]["w1"]["matched"] == 1
    assert r["possession"]["team_in_possession_agree"] == "3/3"
    assert 0 <= r["w1"]["chance_recall"] <= 1
