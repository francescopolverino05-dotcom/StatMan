"""Scoreboard ("score bug") reader: match clock + score from the broadcast overlay.

Run once per match before tagging. Samples one frame every ``step`` seconds
(ffmpeg, top-left crop only), locates the white score box, OCRs the score box
and the clock to its left with tesseract (CLI, apt ``tesseract-ocr``), and
optionally falls back to a cheap vision LLM on the *crop only*.

Readings are smoothed:
* clock: per-half linear fit (video_s -> match_s, slope ~1) using RANSAC-like
  inlier voting, so OCR glitches are ignored; a clock reset (e.g. 45:00 again
  or a big jump back) after a gap starts the second half.
* score: per-team monotonic; a new score must be read in ``persist`` consecutive
  valid samples (majority) and never go back, otherwise it is ignored.

Toggle with ``STATMAN_SCOREBUG=auto|off`` (default auto). Anything missing
(no tesseract, no bug on screen) -> ``{"enabled": False, ...}``; nothing breaks.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("statman.autotag.scorebug")

CROP = (0.0, 0.0, 0.40, 0.16)  # x, y, w, h fractions: top-left score bug region
GOAL_CONFIDENCE = 0.95
HALF_SECONDS = 45 * 60
FALLBACK_MODEL = "google/gemini-2.5-flash"
_CLOCK_RE = re.compile(r"(\d{1,3})\s*[:.]\s*(\d{2})")
_SCORE_RE = re.compile(r"(\d{1,2})\s*[-–—:]\s*(\d{1,2})")


def goal_lag() -> float:
    try:
        return float(os.environ.get("STATMAN_SCOREBUG_GOAL_LAG_S", "15"))
    except ValueError:
        return 15.0


def mode() -> str:
    v = os.environ.get("STATMAN_SCOREBUG", "auto").strip().lower()
    return "off" if v in {"off", "0", "false", "no"} else "auto"


# ---------------------------------------------------------------- sampling

def sample_crops(video: str | Path, out_dir: str | Path, step: float = 5.0, crop=CROP) -> list[tuple[float, Path]]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    x, y, w, h = crop
    # select on exact timestamps (not the fps filter, whose rounding shifts samples by ~half a step)
    vf = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step - 0.02})',showinfo," \
         f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}"
    r = subprocess.run(["ffmpeg", "-v", "info", "-nostats", "-y", "-i", str(video), "-vf", vf, "-vsync", "0",
                        "-q:v", "2", str(out / "sb_%05d.png")], check=True, capture_output=True, text=True)
    times = [float(m) for m in re.findall(r"pts_time:\s*([0-9.]+)", r.stderr)]
    files = sorted(out.glob("sb_*.png"))
    if len(times) != len(files):
        times = [i * step for i in range(len(files))]
    return list(zip(times, files))


# ---------------------------------------------------------------- OCR

def _tess(img, whitelist: str) -> str:
    import cv2

    ok, buf = cv2.imencode(".png", img)
    r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", "7", "-c", f"tessedit_char_whitelist={whitelist}"],
                       input=buf.tobytes(), capture_output=True, timeout=20,
                       env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return r.stdout.decode(errors="ignore").strip()


def locate_box(img) -> tuple[int, int, int, int] | None:
    """Largest bright, wide rectangle (the white score box) in the crop."""

    import cv2

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 200), (180, 40, 255))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = img.shape[:2]
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < W * 0.12 or h < H * 0.12 or w > W * 0.5 or not (1.2 < w / h < 5):
            continue
        if cv2.contourArea(c) < 0.7 * w * h:
            continue
        if best is None or w * h > best[2] * best[3]:
            best = (x, y, w, h)
    return best


def _prep(region, invert: bool):
    import cv2

    g = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if invert:
        b = 255 - b
    return cv2.copyMakeBorder(b, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)


def locate_bar(img) -> tuple[int, int, int, int] | None:
    """Dark-blue overlay bar (wide, short) in the crop."""

    import cv2

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (100, 80, 20), (130, 255, 160))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 9)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    H, W = img.shape[:2]
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w < W * 0.5 or h < H * 0.3 or not (3 < w / h < 10):
            continue
        if best is None or w * h > best[2] * best[3]:
            best = (x, y, w, h)
    return best


def read_crop_ocr(img) -> dict[str, Any] | None:
    """None = no score bug found; else {clock, score} (either may be None)."""

    bar = locate_bar(img)
    box = locate_box(img)
    if box is not None and bar is not None:
        bx, by, bw, bh = box
        if not (bar[0] <= bx and bx + bw <= bar[0] + bar[2] + 2):
            box = None
    if box is None and bar is None:
        return None
    if box is not None:
        x, y, w, h = box
        mx, my = int(0.12 * w), int(0.1 * h)
        score = img[y + my:y + h - my, x + mx:x + w - mx]
        cx0 = bar[0] + int(0.01 * bar[2]) if bar else max(0, int(x - 1.55 * w))
        cx1 = bar[0] + int(0.18 * bar[2]) if bar else max(0, int(x - 0.85 * w))
        clock = img[y + my:y + h - my, cx0:cx1]
    else:
        x, y, w, h = bar
        y0 = y + int(0.42 * h)
        score = img[y0:y + h, x + int(0.43 * w):x + int(0.63 * w)]
        clock = img[y0:y + h, x + int(0.01 * w):x + int(0.18 * w)]
    score_txt = _tess(_prep(score, False), "0123456789-") if score.size else ""
    clock_txt = _tess(_prep(clock, True), "0123456789:") if clock.size else ""
    return parse(clock_txt, score_txt)


def parse(clock_txt: str, score_txt: str) -> dict[str, Any]:
    out: dict[str, Any] = {"clock": None, "score": None}
    m = _CLOCK_RE.search(clock_txt or "")
    if m and int(m.group(2)) < 60 and int(m.group(1)) <= 130:
        out["clock"] = int(m.group(1)) * 60 + int(m.group(2))
    s = _SCORE_RE.search(score_txt or "")
    if s is None and score_txt and re.fullmatch(r"\d\d", score_txt.strip()):  # dash lost
        s = re.match(r"(\d)(\d)", score_txt.strip())
    if s and int(s.group(1)) < 20 and int(s.group(2)) < 20:
        out["score"] = (int(s.group(1)), int(s.group(2)))
    return out


def read_crop_llm(path: Path, api_key: str, model: str = FALLBACK_MODEL) -> tuple[dict[str, Any] | None, float]:
    """Vision fallback on the crop only. Returns (reading, cost_usd)."""

    import httpx

    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    body = {"model": model, "max_tokens": 60, "temperature": 0, "usage": {"include": True},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": 'Football score bug. Reply only JSON {"clock":"MM:SS","home":int,"away":int} '
                                         'or {"none":true} if no scoreboard is visible.'},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]}
    r = httpx.post(os.environ.get("TAGGER_API_URL", "https://openrouter.ai/api/v1/chat/completions"),
                   headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=60)
    r.raise_for_status()
    j = r.json()
    cost = float((j.get("usage") or {}).get("cost") or 0.0)
    txt = j["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return None, cost
    d = json.loads(m.group(0))
    if d.get("none"):
        return None, cost
    return parse(str(d.get("clock") or ""), f"{d.get('home')}-{d.get('away')}"), cost


# ---------------------------------------------------------------- smoothing

def fit_clock(readings: list[dict[str, Any]], tol: float = 3.0, min_inliers: int = 6) -> list[dict[str, Any]]:
    """Greedy segment extraction: offset = clock - video_s is constant within a half."""

    pts = [(r["video_s"], r["clock"]) for r in readings if r.get("clock") is not None]
    segs: list[dict[str, Any]] = []
    remaining = pts[:]
    while len(remaining) >= min_inliers:
        votes = Counter(round((c - v) / tol) for v, c in remaining)
        key, n = votes.most_common(1)[0]
        inl = [(v, c) for v, c in remaining if abs((c - v) - key * tol) <= tol * 1.5]
        if len(inl) < min_inliers:
            break
        off = sorted(c - v for v, c in inl)[len(inl) // 2]
        inl = [(v, c) for v, c in inl if abs((c - v) - off) <= tol]
        vs = [v for v, _ in inl]
        # keep the dense run only (drop stray matches far away)
        vs.sort()
        segs.append({"video_start": vs[0], "video_end": vs[-1], "offset": off, "n": len(inl)})
        remaining = [(v, c) for v, c in remaining if not (vs[0] <= v <= vs[-1])]
    segs = [s for s in segs if s["n"] >= min_inliers]
    segs.sort(key=lambda s: s["video_start"])
    # merge consecutive pieces with the same offset (the clock just kept running)
    merged: list[dict[str, Any]] = []
    for s in segs:
        if merged and abs(merged[-1]["offset"] - s["offset"]) <= tol:
            merged[-1]["video_end"] = s["video_end"]
            merged[-1]["n"] += s["n"]
        else:
            merged.append(dict(s))
    out = []
    for i, s in enumerate(merged):
        ms = s["video_start"] + s["offset"]
        # Many youth/league feeds restart the bug at 00:00 for the second half:
        # put it on the continuous match clock (2H starts at 45:00).
        if i >= 1 and ms < out[-1]["match_end"] - 60:
            s["offset"] += HALF_SECONDS * i
            ms += HALF_SECONDS * i
        out.append({"period": i + 1, "video_start": round(s["video_start"], 1), "video_end": round(s["video_end"], 1),
                    "match_start": round(ms, 1), "match_end": round(s["video_end"] + s["offset"], 1),
                    "samples": s["n"]})
    for a, b in zip(out, out[1:]):
        a["gap_after_s"] = round(b["video_start"] - a["video_end"], 1)  # half-time gap in the video
    return out


def smooth_score(readings: list[dict[str, Any]], persist: int = 4, window: int = 7) -> list[dict[str, Any]]:
    """Monotonic score timeline. Returns change points [{video_s, score, team}]."""

    seq = [(r["video_s"], tuple(r["score"])) for r in readings if r.get("score") is not None]
    if not seq:
        return []
    # initial score = majority of the first window
    cur = Counter(s for _, s in seq[:window]).most_common(1)[0][0]
    changes = [{"video_s": seq[0][0], "score": list(cur), "team": None}]
    i = 0
    while i < len(seq):
        v, s = seq[i]
        if s != cur and s[0] >= cur[0] and s[1] >= cur[1] and sum(s) == sum(cur) + 1:
            look = [x for _, x in seq[i:i + window]]
            if look.count(s) >= persist and Counter(look).most_common(1)[0][0] == s:
                team = "home" if s[0] > cur[0] else "away"
                changes.append({"video_s": v, "score": list(s), "team": team})
                cur = s
        i += 1
    return changes


def video_to_clock(video_s: float, segments: list[dict[str, Any]]) -> tuple[int, float] | None:
    best = None
    for s in segments:
        if video_s >= s["video_start"] - 60:
            best = s
    if best is None:
        return None
    return best["period"], best["match_start"] + (video_s - best["video_start"])


# ---------------------------------------------------------------- driver

def analyse(video: str | Path, *, step: float = 5.0, work_dir: str | Path | None = None,
            reader: Callable[[Any], dict[str, Any] | None] | None = None,
            llm_fallback: bool | None = None, llm_max_calls: int = 200) -> dict[str, Any]:
    """Full pass over one match video. Never raises for missing tools/overlay."""

    t0 = time.time()
    res: dict[str, Any] = {"enabled": False, "reason": None, "segments": [], "goals": [], "score_timeline": [],
                           "samples": 0, "readable": 0, "llm_calls": 0, "cost_usd": 0.0}
    if mode() == "off":
        res["reason"] = "STATMAN_SCOREBUG=off"
        return res
    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        res["reason"] = f"opencv unavailable: {exc}"
        return res
    if reader is None and shutil.which("tesseract") is None:
        res["reason"] = "tesseract not installed"
        return res
    api_key = os.environ.get("TAGGER_API_KEY", "")
    if llm_fallback is None:
        llm_fallback = bool(api_key) and os.environ.get("STATMAN_SCOREBUG_LLM", "1") != "0"
    tmp = None
    try:
        if work_dir is None:
            tmp = tempfile.TemporaryDirectory(prefix="scorebug_")
            work_dir = tmp.name
        crops = sample_crops(video, work_dir, step=step)
        reader = reader or read_crop_ocr

        def _one(item):
            vs, f = item
            img = cv2.imread(str(f))
            return vs, f, (reader(img) if img is not None else None)

        from concurrent.futures import ThreadPoolExecutor

        workers = max(1, min(int(os.environ.get("STATMAN_SCOREBUG_WORKERS", "4")), 8))
        with ThreadPoolExecutor(workers) as ex:
            raw = list(ex.map(_one, crops))
        readings = []
        for vs, f, r in raw:
            # Vision fallback only where a bug exists but OCR could not parse it.
            if llm_fallback and r is not None and (r["clock"] is None or r["score"] is None) \
                    and res["llm_calls"] < llm_max_calls:
                try:
                    r2, cost = read_crop_llm(f, api_key)
                    res["llm_calls"] += 1
                    res["cost_usd"] += cost
                    if r2:
                        r = {"clock": r["clock"] if r["clock"] is not None else r2["clock"],
                             "score": r["score"] if r["score"] is not None else r2["score"], "llm": True}
                except Exception as exc:  # noqa: BLE001 - never log the key / response body
                    log.warning("scorebug llm fallback failed: %s", type(exc).__name__)
            readings.append({"video_s": vs, **(r or {"clock": None, "score": None})})
        res.update(summarise(readings))
    except Exception as exc:  # noqa: BLE001
        log.exception("scorebug failed")
        res["reason"] = f"scorebug error: {exc}"
        res["enabled"] = False
    finally:
        if tmp is not None:
            tmp.cleanup()
    res["runtime_s"] = round(time.time() - t0, 1)
    res["cost_usd"] = round(res["cost_usd"], 5)
    return res


def summarise(readings: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"samples": len(readings),
                           "readable": sum(1 for r in readings if r.get("clock") is not None or r.get("score")),
                           "readings": readings}
    segs = fit_clock(readings)
    timeline = smooth_score(readings)
    goals = []
    for ch in timeline[1:]:
        # The bug updates after the celebration: estimate the strike GOAL_LAG_S earlier.
        vt = max(0.0, ch["video_s"] - goal_lag())
        pc = video_to_clock(vt, segs)
        goals.append({"type": "goal", "team": ch["team"], "video_ts_seconds": round(vt, 1),
                      "score_change_video_s": round(ch["video_s"], 1),
                      "t_match_seconds": round(pc[1], 1) if pc else None, "period": pc[0] if pc else None,
                      "minute": int(pc[1] // 60) + 1 if pc else None, "score_after": ch["score"],
                      "confidence": GOAL_CONFIDENCE, "source": "scorebug"})
    out.update(segments=segs, score_timeline=timeline, goals=goals)
    out["enabled"] = bool(segs)
    out["reason"] = None if segs else "score bug not found / unreadable"
    return out


# ---------------------------------------------------------------- pipeline hooks

def clip_segments(sb: dict[str, Any]) -> list[dict[str, Any]]:
    """Segments in the format ``clips.plan_clips`` expects."""

    return [{"video_start": s["video_start"], "match_start": s["match_start"]} for s in sb.get("segments") or []]


def reconcile_goals(events: list[dict[str, Any]], sb: dict[str, Any], window: float = 90.0) -> list[dict[str, Any]]:
    """(b) insert confirmed goals; (c) AI goals without a score change -> shot candidate, pending review.

    The score bug updates some seconds after the ball goes in, so an AI goal
    up to ``window`` s before a confirmed change is matched (and keeps its exact time).
    """

    if not sb.get("enabled"):
        return events
    confirmed = [dict(g) for g in sb.get("goals") or []]
    used: set[int] = set()
    out = []
    for ev in events:
        if ev.get("type") != "goal":
            out.append(ev)
            continue
        vt = ev.get("video_ts_seconds")
        hit = None
        for i, g in enumerate(confirmed):
            if i in used or vt is None:
                continue
            ref = g.get("score_change_video_s", g["video_ts_seconds"])
            if -15 <= ref - vt <= window and ev.get("team") in (None, g["team"]):
                hit = i
                break
        if hit is not None:
            used.add(hit)
            ev = {**ev, "confidence": max(ev.get("confidence") or 0, GOAL_CONFIDENCE), "team": confirmed[hit]["team"],
                  "attributes": {**(ev.get("attributes") or {}), "scorebug_confirmed": True}}
            out.append(ev)
        else:
            out.append({**ev, "type": "shot", "confidence": min(ev.get("confidence") or 0.3, 0.3),
                        "attributes": {k: v for k, v in (ev.get("attributes") or {}).items() if k == "headed"},
                        "issues": list(ev.get("issues") or []) + ["AI goal not backed by score change (disallowed?)"],
                        "review_status": "pending"})
    for i, g in enumerate(confirmed):
        if i in used or g.get("t_match_seconds") is None:
            continue
        out.append({"type": "goal", "team": g["team"], "shirt": None, "player": None,
                    "t_match_seconds": g["t_match_seconds"], "video_ts_seconds": g["video_ts_seconds"],
                    "period": g["period"], "x": None, "y": None,
                    "attributes": {"scorebug_confirmed": True}, "confidence": GOAL_CONFIDENCE,
                    "clip_ids": [], "issues": ["scorer unknown (from score bug)"]})
    return sorted(out, key=lambda e: e["t_match_seconds"])
