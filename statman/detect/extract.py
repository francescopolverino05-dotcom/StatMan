"""Per-frame detection: people (with torso kit colour) and ball candidates."""
from __future__ import annotations

import gzip
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

PERSON_NAMES = {"person", "player", "goalkeeper", "referee"}
BALL_NAMES = {"ball", "sports ball"}


@dataclass
class Person:
    box: tuple[float, float, float, float]
    conf: float
    color: tuple[float, float, float] | None  # torso median in Lab (OpenCV 0-255 scale)
    role: str = "person"  # person / player / goalkeeper / referee (depends on the weights)

    @property
    def feet(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2, self.box[3])

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class Ball:
    x: float
    y: float
    conf: float
    size: float


@dataclass
class Frame:
    t: float
    persons: list[Person] = field(default_factory=list)
    balls: list[Ball] = field(default_factory=list)
    green: float = 1.0  # share of grass pixels (low = close-up / replay / crowd)


def grass_mask(img: np.ndarray) -> np.ndarray:
    import cv2
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, (30, 40, 40), (90, 255, 255)) > 0


def torso_color(img: np.ndarray, box, grass: np.ndarray) -> tuple[float, float, float] | None:
    """Mean Lab colour of the shirt area (upper-middle of the box), grass pixels removed."""
    import cv2
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    h, w = y2 - y1, x2 - x1
    if h < 8 or w < 3:
        return None
    ty1, ty2 = y1 + int(0.15 * h), y1 + int(0.5 * h)
    tx1, tx2 = x1 + int(0.2 * w), x2 - int(0.2 * w)
    H, W = img.shape[:2]
    ty1, ty2, tx1, tx2 = max(ty1, 0), min(ty2, H), max(tx1, 0), min(tx2, W)
    if ty2 <= ty1 or tx2 <= tx1:
        return None
    patch = img[ty1:ty2, tx1:tx2]
    keep = ~grass[ty1:ty2, tx1:tx2]
    if keep.sum() < 4:
        return None
    lab = cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)[keep]
    return tuple(float(v) for v in np.median(lab, axis=0))


def iter_frames(video: str | Path, fps: float, start: float = 0.0, duration: float | None = None) -> Iterator[tuple[float, np.ndarray]]:
    """Decode sequentially and yield (t_seconds_from_video_start, BGR frame) at ~fps."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(video)
    src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    step = 1.0 / fps
    nxt = start
    end = None if duration is None else start + duration
    idx = int(round(start * src))
    while True:
        ok = cap.grab()
        if not ok:
            break
        t = idx / src
        idx += 1
        if end is not None and t >= end:
            break
        if t + 1e-6 >= nxt:
            ok, img = cap.retrieve()
            if not ok:
                break
            yield t, img
            nxt += step
    cap.release()


def detect_video(video: str | Path, fps: float = 8.0, start: float = 0.0, duration: float | None = None,
                 weights: str = "yolov8n.pt", imgsz: int = 1280, person_conf: float = 0.25,
                 ball_conf: float = 0.02, progress: bool = False) -> list[Frame]:
    from ultralytics import YOLO
    model = YOLO(weights)
    names = model.names
    keep_cls = [k for k, v in names.items() if v in PERSON_NAMES | BALL_NAMES]
    frames: list[Frame] = []
    t0 = time.time()
    for t, img in iter_frames(video, fps, start, duration):
        g = grass_mask(img)
        H = img.shape[0]
        r = model.predict(img, imgsz=imgsz, classes=keep_cls, conf=ball_conf, verbose=False)[0]
        fr = Frame(t=round(t, 3), green=float(g[H // 3:].mean()))
        for (x1, y1, x2, y2), c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist()):
            name = names[int(k)]
            if name in PERSON_NAMES:
                if c < person_conf:
                    continue
                fx, fy = int((x1 + x2) / 2), int(min(y2, H - 1))
                # feet must be on (or right next to) grass
                ys, xs = slice(max(fy - 3, 0), fy + 4), slice(max(fx - 4, 0), fx + 5)
                if g[ys, xs].mean() < 0.15:
                    continue
                fr.persons.append(Person((x1, y1, x2, y2), round(c, 3), torso_color(img, (x1, y1, x2, y2), g), name))
            elif name in BALL_NAMES:
                fr.balls.append(Ball((x1 + x2) / 2, (y1 + y2) / 2, round(c, 3), max(x2 - x1, y2 - y1)))
        frames.append(fr)
        if progress and len(frames) % 100 == 0:
            print(f"{t:.1f}s {len(frames)} frames {time.time() - t0:.0f}s", flush=True)
    return frames


def save(frames: list[Frame], path: str | Path) -> None:
    data = [{"t": f.t, "g": round(f.green, 3),
             "p": [[*(round(v, 1) for v in p.box), p.conf, None if p.color is None else [round(v, 1) for v in p.color], p.role] for p in f.persons],
             "b": [[round(b.x, 1), round(b.y, 1), b.conf, round(b.size, 1)] for b in f.balls]} for f in frames]
    with gzip.open(path, "wt") as fh:
        json.dump(data, fh)


def load(path: str | Path) -> list[Frame]:
    with gzip.open(path, "rt") as fh:
        data = json.load(fh)
    return [Frame(t=d["t"], green=d.get("g", 1.0),
                  persons=[Person(tuple(p[:4]), p[4], None if p[5] is None else tuple(p[5]), p[6] if len(p) > 6 else "person") for p in d["p"]],
                  balls=[Ball(*b) for b in d["b"]]) for d in data]
