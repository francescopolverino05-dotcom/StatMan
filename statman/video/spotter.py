"""Approximate SoccerNet-style action spotting for a full-match video.

Designed for 90–120+ minute broadcasts, not short clips. Samples the whole
timeline sparsely (default 0.5 fps), finds people (HOG), tracks motion peaks as
a ball proxy, and emits SoccerNet Ball Action Spotting classes:

Pass, Drive, Header, High Pass, Out, Cross, Throw In, Shot,
Ball Player Block, Player Successful Tackle, Free Kick, Goal.

Results are approximate — fine for film workflow, not Opta/StatsBomb grade.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ACTION_CLASSES = (
    "Pass",
    "Drive",
    "Header",
    "High Pass",
    "Out",
    "Cross",
    "Throw In",
    "Shot",
    "Ball Player Block",
    "Player Successful Tackle",
    "Free Kick",
    "Goal",
)

ProgressCb = Callable[[float, float, int], None]  # time_sec, duration_sec, event_count


@dataclass
class SpotConfig:
    """Defaults tuned for a full match on CPU."""

    sample_fps: float = 0.5  # one frame every 2s → ~2700 frames for 90'
    # Hard ceiling so a corrupt/endless stream cannot run forever.
    # 0.5 fps × 150 minutes = 4500 sampled frames.
    max_duration_sec: float = 150 * 60
    min_gap_sec: float = 1.2
    hog_scale: float = 1.08
    hog_win_stride: tuple[int, int] = (8, 8)
    resize_fx: float = 0.4  # smaller frames = workable full-match runtime


def spot_actions(
    video_path: Path,
    config: SpotConfig | None = None,
    on_progress: ProgressCb | None = None,
) -> list[dict[str, Any]]:
    """Spot approximate actions across the full video duration."""
    cfg = config or SpotConfig()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if src_fps <= 1e-3:
        src_fps = 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / src_fps if frame_count > 0 else 0.0
    if duration <= 0:
        # Fallback: read until EOF; still capped by max_duration_sec
        duration = cfg.max_duration_sec
    duration = min(duration, cfg.max_duration_sec)

    frame_step = max(int(round(src_fps / cfg.sample_fps)), 1)
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    prev_gray = None
    prev_ball: tuple[float, float] | None = None
    prev_handler: tuple[float, float] | None = None
    events: list[dict[str, Any]] = []
    last_event_t = -1e9
    frame_idx = 0
    sampled = 0
    last_report = -1.0

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t = frame_idx / src_fps
        if t > cfg.max_duration_sec:
            break

        if frame_idx % frame_step != 0:
            frame_idx += 1
            continue

        small = cv2.resize(frame, (0, 0), fx=cfg.resize_fx, fy=cfg.resize_fx)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)

        people = _detect_people(hog, small, cfg)
        ball = _detect_ball_proxy(gray_blur, prev_gray)
        handler = _nearest_person(people, ball) if ball and people else None

        motion_score = 0.0
        if prev_gray is not None:
            diff = cv2.absdiff(gray_blur, prev_gray)
            motion_score = float(np.mean(diff))

        label = _classify_transition(
            t=t,
            last_event_t=last_event_t,
            min_gap=cfg.min_gap_sec,
            ball=ball,
            prev_ball=prev_ball,
            handler=handler,
            prev_handler=prev_handler,
            people=people,
            motion_score=motion_score,
            frame_w=small.shape[1],
            frame_h=small.shape[0],
        )
        if label is not None:
            scale = 1.0 / cfg.resize_fx
            events.append(
                {
                    "time_sec": round(t, 3),
                    "label": label,
                    "confidence": _confidence(label, motion_score, ball is not None, len(people)),
                    "ball_xy": (
                        [round(ball[0] * scale, 1), round(ball[1] * scale, 1)] if ball else None
                    ),
                    "handler_xy": (
                        [round(handler[0] * scale, 1), round(handler[1] * scale, 1)]
                        if handler
                        else None
                    ),
                    "people_count": len(people),
                    "motion": round(motion_score, 2),
                }
            )
            last_event_t = t

        if on_progress and (t - last_report >= 5.0 or t >= duration):
            on_progress(t, duration, len(events))
            last_report = t

        prev_gray = gray_blur
        prev_ball = ball
        prev_handler = handler
        sampled += 1
        frame_idx += 1

    cap.release()
    if on_progress:
        on_progress(min(duration, frame_idx / src_fps), duration, len(events))
    return events


def _detect_people(
    hog: cv2.HOGDescriptor,
    frame: np.ndarray,
    cfg: SpotConfig,
) -> list[tuple[float, float]]:
    rects, weights = hog.detectMultiScale(
        frame,
        winStride=cfg.hog_win_stride,
        padding=(8, 8),
        scale=cfg.hog_scale,
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


def _nearest_person(
    people: list[tuple[float, float]],
    ball: tuple[float, float],
) -> tuple[float, float] | None:
    if not people:
        return None
    bx, by = ball
    return min(people, key=lambda p: (p[0] - bx) ** 2 + (p[1] - by) ** 2)


def _classify_transition(
    *,
    t: float,
    last_event_t: float,
    min_gap: float,
    ball: tuple[float, float] | None,
    prev_ball: tuple[float, float] | None,
    handler: tuple[float, float] | None,
    prev_handler: tuple[float, float] | None,
    people: list[tuple[float, float]],
    motion_score: float,
    frame_w: int,
    frame_h: int,
) -> str | None:
    if t - last_event_t < min_gap:
        return None
    if ball is None or prev_ball is None:
        return None

    bx, by = ball
    px, py = prev_ball
    dx, dy = bx - px, by - py
    speed = float(np.hypot(dx, dy))
    near_sideline = bx < frame_w * 0.06 or bx > frame_w * 0.94
    near_goal_line = by < frame_h * 0.12 or by > frame_h * 0.88
    high_ball = by < frame_h * 0.35

    handler_changed = False
    if handler and prev_handler:
        dist = float(np.hypot(handler[0] - prev_handler[0], handler[1] - prev_handler[1]))
        handler_changed = dist > 22

    if near_goal_line and speed > 12 and motion_score > 10:
        if motion_score > 24 and speed > 18:
            return "Goal"
        return "Shot"

    if near_sideline and speed > 8:
        return "Out"

    if handler_changed and speed > 5:
        if high_ball and speed > 8:
            return "Header" if abs(dy) > abs(dx) else "High Pass"
        if speed > 14 and abs(dx) > abs(dy) * 1.2:
            return "Cross"
        if motion_score > 18 and speed < 10:
            return "Player Successful Tackle"
        if motion_score > 14 and speed < 9:
            return "Ball Player Block"
        return "Pass"

    if handler and prev_handler and not handler_changed and speed > 4:
        return "Drive"

    if motion_score > 12 and speed > 14 and by > frame_h * 0.55:
        return "Free Kick"

    if speed > 10 and high_ball:
        return "High Pass"

    if speed > 8 and abs(dx) > abs(dy) * 1.4:
        return "Cross"

    if handler_changed:
        return "Throw In" if near_sideline else "Pass"

    return None


def _confidence(label: str, motion: float, has_ball: bool, n_people: int) -> float:
    base = {
        "Pass": 0.45,
        "Drive": 0.35,
        "Header": 0.3,
        "High Pass": 0.35,
        "Out": 0.4,
        "Cross": 0.35,
        "Throw In": 0.25,
        "Shot": 0.4,
        "Ball Player Block": 0.25,
        "Player Successful Tackle": 0.3,
        "Free Kick": 0.25,
        "Goal": 0.35,
    }.get(label, 0.3)
    bump = 0.0
    if has_ball:
        bump += 0.1
    if n_people >= 3:
        bump += 0.05
    if motion > 12:
        bump += 0.05
    return round(min(base + bump, 0.85), 3)
