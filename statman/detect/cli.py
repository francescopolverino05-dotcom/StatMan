"""Command line: ``python -m statman.detect.cli VIDEO --out moments.json [--hand hand.txt --offset 960]``.

Runs locally on CPU (ultralytics YOLO + OpenCV); no network or paid API calls.
Weights: any ultralytics detector with person/ball classes. A football-specific
model with a ``ball`` class (e.g. HF ``uisikdag/yolo-v8-football-players-detection``
best.pt) finds the 3-5 px ball far more often than COCO ``yolov8n.pt``.
Weights and videos are never committed.
"""
from __future__ import annotations

import argparse
import json
import time

from . import camera, evaluate, extract, moments, teams


def run(video, weights: str, fps: float = 8.0, imgsz: int = 1280, start: float = 0.0, duration: float | None = None,
        home_hint=None, away_hint=None, cache: str | None = None, cfg: moments.DetectConfig | None = None) -> dict:
    t0 = time.time()
    frames = extract.load(cache) if cache and _exists(cache) else extract.detect_video(
        video, fps=fps, start=start, duration=duration, weights=weights, imgsz=imgsz)
    if cache and not _exists(cache):
        extract.save(frames, cache)
    t1 = time.time()
    pan = camera.pan_events(camera.pan_series(video, fps=fps, start=start, duration=duration))
    tm = teams.TeamModel.fit([p.color for f in frames for p in f.persons if p.role in ("person", "player")],
                             home_hint=home_hint, away_hint=away_hint)
    ms = moments.detect(frames, tm, cfg, pan=pan)
    t2 = time.time()
    span = (frames[-1].t - frames[0].t) if len(frames) > 1 else 0.0
    return {"video": str(video), "start": start, "fps": fps, "weights": weights, "imgsz": imgsz,
            "timing_s": {"detect": round(t1 - t0, 1), "post": round(t2 - t1, 1),
                         "per_video_min": round((t2 - t0) / max(span / 60, 1e-9), 1) if span else None},
            "teams": {"home_lab": tm.home.round(1).tolist(), "away_lab": tm.away.round(1).tolist()},
            "moments": [m.to_dict() for m in ms]}


def _exists(p) -> bool:
    from pathlib import Path
    return Path(p).exists()


def _bgr(s: str | None):
    return None if not s else tuple(int(v) for v in s.split(","))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video")
    ap.add_argument("--weights", default="yolov8n.pt")
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float)
    ap.add_argument("--home-bgr", help="home kit reference colour B,G,R e.g. 225,170,90")
    ap.add_argument("--away-bgr", help="away kit reference colour B,G,R")
    ap.add_argument("--cache", help="detections cache (.json.gz), reused if present")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hand", help="hand tags to score against")
    ap.add_argument("--offset", type=float, default=0.0, help="match seconds = video seconds + offset")
    ap.add_argument("--home-name", default="Napoli")
    a = ap.parse_args(argv)
    res = run(a.video, a.weights, a.fps, a.imgsz, a.start, a.duration, _bgr(a.home_bgr), _bgr(a.away_bgr), a.cache)
    if a.hand:
        hand = evaluate.load_hand(a.hand, a.home_name)
        lo = a.start + a.offset
        hi = lo + (a.duration or (res["moments"][-1]["t"] - a.start if res["moments"] else 0))
        res["eval"] = evaluate.score([h for h in hand if lo <= h.t < hi], res["moments"], a.offset, lo, hi)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "moments"}, indent=1))


if __name__ == "__main__":
    main()
