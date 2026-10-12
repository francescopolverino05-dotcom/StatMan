"""Person + ball detectors for full-match spotting.

Prefers a YOLO COCO model (person / sports ball). Falls back to OpenCV HOG
people detection + motion-based ball proxy when YOLO is unavailable.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

log = logging.getLogger(__name__)

# COCO class ids
_PERSON = 0
_SPORTS_BALL = 32

_WEIGHTS = Path(__file__).resolve().parent.parent.parent / ".data" / "models" / "yolov8n.pt"

_YOLO_LOCK = threading.Lock()
_YOLO_MODEL: Any | None = None
_YOLO_TRIED = False
_YOLO_ERROR: str | None = None


@dataclass
class Detections:
    people: list[tuple[float, float]]
    ball: tuple[float, float] | None
    backend: str  # "yolo" | "opencv-hog"


def detector_backend() -> str:
    """Return the active detector name without forcing a model load."""
    if _YOLO_MODEL is not None:
        return "yolo"
    if _YOLO_TRIED and _YOLO_MODEL is None:
        return "opencv-hog"
    return "yolo-or-opencv"  # decided on first frame


def yolo_status(*, ensure_loaded: bool = False) -> dict[str, Any]:
    if ensure_loaded:
        _load_yolo()
    return {
        "available": _YOLO_MODEL is not None,
        "tried": _YOLO_TRIED,
        "error": _YOLO_ERROR,
        "backend": "yolo" if _YOLO_MODEL is not None else "opencv-hog",
        "weights": str(_WEIGHTS) if _WEIGHTS.exists() else "yolov8n.pt",
    }


def _load_yolo() -> Any | None:
    global _YOLO_MODEL, _YOLO_TRIED, _YOLO_ERROR
    with _YOLO_LOCK:
        if _YOLO_TRIED:
            return _YOLO_MODEL
        _YOLO_TRIED = True
        try:
            from ultralytics import YOLO

            # YOLOv8n COCO — person (0) + sports ball (32). SoccerNet action
            # weights are heavier; this is the practical CPU full-match spotter.
            weights = str(_WEIGHTS) if _WEIGHTS.exists() else "yolov8n.pt"
            _YOLO_MODEL = YOLO(weights)
            log.info("YOLO detector ready (%s)", weights)
        except Exception as exc:  # noqa: BLE001 - keep spotting alive on CPU-only hosts
            _YOLO_ERROR = str(exc)
            _YOLO_MODEL = None
            log.warning("YOLO unavailable, using OpenCV HOG fallback: %s", exc)
        return _YOLO_MODEL


def detect_frame(
    frame_bgr: np.ndarray,
    *,
    prev_gray: np.ndarray | None,
    gray_blur: np.ndarray,
    hog: cv2.HOGDescriptor | None,
    hog_scale: float,
    hog_win_stride: tuple[int, int],
    prefer_yolo: bool = True,
) -> Detections:
    """Detect people + ball on one (possibly resized) BGR frame."""
    if prefer_yolo:
        model = _load_yolo()
        if model is not None:
            try:
                return _detect_yolo(model, frame_bgr)
            except Exception as exc:  # noqa: BLE001
                log.warning("YOLO inference failed, falling back to HOG: %s", exc)

    people = _detect_people_hog(hog, frame_bgr, hog_scale, hog_win_stride) if hog else []
    ball = _detect_ball_proxy(gray_blur, prev_gray)
    return Detections(people=people, ball=ball, backend="opencv-hog")


def _detect_yolo(model: Any, frame_bgr: np.ndarray) -> Detections:
    # conf modest — broadcast frames are small after resize_fx
    results = model.predict(frame_bgr, verbose=False, conf=0.25, classes=[_PERSON, _SPORTS_BALL])
    people: list[tuple[float, float]] = []
    ball: tuple[float, float] | None = None
    best_ball_conf = 0.0
    if not results:
        return Detections(people=people, ball=None, backend="yolo")
    r0 = results[0]
    boxes = getattr(r0, "boxes", None)
    if boxes is None:
        return Detections(people=people, ball=None, backend="yolo")
    xyxy = boxes.xyxy.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    conf = boxes.conf.cpu().numpy()
    for (x1, y1, x2, y2), c, cf in zip(xyxy, cls, conf):
        cx = float((x1 + x2) / 2)
        if int(c) == _PERSON:
            # foot-ish anchor for handler association
            cy = float(y1 + (y2 - y1) * 0.65)
            people.append((cx, cy))
        elif int(c) == _SPORTS_BALL and float(cf) > best_ball_conf:
            best_ball_conf = float(cf)
            ball = (cx, float((y1 + y2) / 2))
    return Detections(people=people, ball=ball, backend="yolo")


def _detect_people_hog(
    hog: cv2.HOGDescriptor | None,
    frame: np.ndarray,
    hog_scale: float,
    hog_win_stride: tuple[int, int],
) -> list[tuple[float, float]]:
    if hog is None:
        return []
    rects, weights = hog.detectMultiScale(
        frame,
        winStride=hog_win_stride,
        padding=(8, 8),
        scale=hog_scale,
    )
    centres: list[tuple[float, float]] = []
    weight_list = list(weights) if weights is not None else [1.0] * len(rects)
    for (x, y, w, h), weight in zip(rects, weight_list):
        if float(weight) < 0.35:
            continue
        centres.append((float(x + w / 2), float(y + h * 0.65)))
    return centres


def _detect_ball_proxy(
    gray: np.ndarray,
    prev_gray: np.ndarray | None,
) -> tuple[float, float] | None:
    if prev_gray is None:
        return None
    diff = cv2.absdiff(gray, prev_gray)
    _, thr = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    h, w = gray.shape
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 6 or area > (h * w) * 0.012:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw / max(bh, 1)
        if aspect < 0.35 or aspect > 2.8:
            continue
        cx, cy = x + bw / 2, y + bh / 2
        edge_pen = 20.0 if (cx < 8 or cy < 8 or cx > w - 8 or cy > h - 8) else 0.0
        score = float(area) - edge_pen
        if score > best_score:
            best_score = score
            best = (float(cx), float(cy))
    return best
