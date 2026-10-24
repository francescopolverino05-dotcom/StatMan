"""Score bug reader. All images/readings here are synthetic TEST DATA."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from statman.autotag import jobs, scorebug, store
from statman.autotag.repo import FileEventRepo
from statman.autotag.tagger import FixtureTagger

from tests.test_autotag import FIXTURE, autotag_root, video_25s  # noqa: F401 - fixtures


def _bug_image(clock: str, score: str):
    """TEST DATA: a 512x114 crop imitating a broadcast score bug."""
    import cv2
    import numpy as np

    img = np.full((114, 512, 3), (235, 200, 150), np.uint8)  # light sky
    cv2.rectangle(img, (28, 28), (472, 104), (90, 30, 10), -1)  # dark blue bar
    cv2.rectangle(img, (205, 60), (322, 100), (255, 255, 255), -1)  # white score box
    cv2.putText(img, clock, (36, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(img, score, (225, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2)
    cv2.putText(img, "HOME", (115, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return img


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_ocr_synthetic_bug():
    r = scorebug.read_crop_ocr(_bug_image("31:04", "1-0"))
    assert r == {"clock": 31 * 60 + 4, "score": (1, 0)}


def test_ocr_no_bug_returns_none():
    import numpy as np

    assert scorebug.read_crop_ocr(np.full((114, 512, 3), (40, 160, 40), np.uint8)) is None


def test_parse():
    assert scorebug.parse("09:54", "0 - 0") == {"clock": 594, "score": (0, 0)}
    assert scorebug.parse("9:7x", "10")["score"] == (1, 0)
    assert scorebug.parse("", "")["clock"] is None


def _readings():
    """TEST DATA: 1H video 0..2880 (clock = v - 6), 10 s cut, 2H clock restarts at 0.
    Goal for home shows on the bug at video 1870; a 2-sample flicker 1-1 at 4400
    (disallowed goal) and OCR junk sprinkled in."""
    rs = []
    for v in range(0, 5800, 5):
        if v <= 2885:
            clock = v - 6 if v >= 6 else None
        elif v >= 2895:
            clock = v - 2893
        else:
            clock = None
        score = (1, 0) if v >= 1870 else (0, 0)
        if v in (4400, 4405):
            score = (1, 1)
        if v % 97 == 0:
            clock, score = 9999 % 3600, (4, 0)
        if v % 53 == 0:
            clock, score = None, None
        rs.append({"video_s": float(v), "clock": clock, "score": score})
    return rs


def test_summarise_clock_and_goals():
    out = scorebug.summarise(_readings())
    assert out["enabled"]
    p1, p2 = out["segments"]
    assert p1["period"] == 1 and abs(p1["match_start"] - (p1["video_start"] - 6)) < 2
    assert p2["period"] == 2 and abs((p2["match_start"] - p2["video_start"]) - (2700 - 2893)) < 2
    assert p1["gap_after_s"] >= 5
    assert [g["team"] for g in out["goals"]] == ["home"]  # flicker ignored, no 4-0
    g = out["goals"][0]
    assert g["score_change_video_s"] == 1870 and g["period"] == 1 and g["minute"] == 31
    assert g["confidence"] == scorebug.GOAL_CONFIDENCE
    assert scorebug.video_to_clock(4200, out["segments"])[1] == pytest.approx(2700 + 4200 - 2893, abs=2)


def test_summarise_unreadable():
    out = scorebug.summarise([{"video_s": float(v), "clock": None, "score": None} for v in range(0, 300, 5)])
    assert not out["enabled"] and out["goals"] == []


def test_reconcile_goals():
    sb = {"enabled": True, "goals": [{"type": "goal", "team": "home", "video_ts_seconds": 1855.0,
                                      "score_change_video_s": 1870.0, "t_match_seconds": 1849.0, "period": 1}]}
    ai = [
        {"type": "goal", "team": "home", "video_ts_seconds": 1858.0, "t_match_seconds": 1852.0, "confidence": 0.6,
         "attributes": {}},
        {"type": "goal", "team": "away", "video_ts_seconds": 4390.0, "t_match_seconds": 4197.0, "confidence": 0.8,
         "attributes": {"headed": True}},
        {"type": "pass", "team": "home", "video_ts_seconds": 10.0, "t_match_seconds": 4.0, "confidence": 0.9,
         "attributes": {}},
    ]
    out = scorebug.reconcile_goals(ai, sb)
    goals = [e for e in out if e["type"] == "goal"]
    assert len(goals) == 1 and goals[0]["confidence"] >= 0.95 and goals[0]["t_match_seconds"] == 1852.0
    shot = next(e for e in out if e["type"] == "shot")
    assert shot["confidence"] <= 0.3 and shot["review_status"] == "pending" and "disallowed" in shot["issues"][-1]
    # No AI goal at all -> the confirmed one is inserted.
    out2 = scorebug.reconcile_goals([], sb)
    assert out2[0]["type"] == "goal" and out2[0]["confidence"] == 0.95
    # Disabled score bug changes nothing.
    assert scorebug.reconcile_goals(ai, {"enabled": False}) == ai


def test_off_toggle(monkeypatch, tmp_path):
    monkeypatch.setenv("STATMAN_SCOREBUG", "off")
    r = scorebug.analyse(tmp_path / "missing.mp4")
    assert r["enabled"] is False and "off" in r["reason"]


def test_missing_bug_graceful(monkeypatch, video_25s):  # noqa: F811
    monkeypatch.delenv("TAGGER_API_KEY", raising=False)
    r = scorebug.analyse(video_25s, step=5)
    assert r["enabled"] is False and r["goals"] == []


def test_job_uses_scorebug(autotag_root, video_25s, monkeypatch):  # noqa: F811
    fake = {"enabled": True, "segments": [{"period": 1, "video_start": 0.0, "match_start": 600.0,
                                           "video_end": 25.0, "match_end": 625.0}],
            "goals": [{"type": "goal", "team": "away", "video_ts_seconds": 12.0, "score_change_video_s": 20.0,
                       "t_match_seconds": 612.0, "period": 1, "confidence": 0.95}]}
    monkeypatch.setattr(scorebug, "analyse", lambda src, **kw: dict(fake))
    jobs.create_job("sb1", video_25s)
    meta = jobs.process_job("sb1", tagger=FixtureTagger(FIXTURE))
    assert meta["status"] == "done" and meta["segments_source"] == "scorebug"
    assert store.read_doc("sb1", "clips")[0]["match_start"] == 600.0
    events = FileEventRepo().list_events("sb1")
    assert any(e["type"] == "goal" and e["team"] == "away" and e["confidence"] == 0.95 for e in events)
    assert all(e["t_match_seconds"] >= 600 for e in events)
