"""Phase 3: team-color clustering + ball-handler possession from broadcast video.

Uses YOLO person/ball boxes (same weights as film spotting), samples torso HSV,
fits two kit clusters with OpenCV k-means, and assigns possession to the cluster
of the person nearest the ball. Clusters are mapped to home/away using anchored
fact goals when available.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from statman.video.detector import get_yolo_model, yolo_status

log = logging.getLogger(__name__)

ProgressCb = Callable[[dict[str, Any]], None]
CancelCb = Callable[[], bool]

_PERSON = 0
_SPORTS_BALL = 32


@dataclass
class TrackingConfig:
    sample_fps: float = 0.25
    resize_fx: float = 0.4
    max_duration_sec: float = 150 * 60
    start_sec: float = 0.0
    conf: float = 0.25
    # Frames used to fit kit clusters (spread across the match).
    fit_samples: int = 60
    min_torso_pixels: int = 24


def _torso_hsv(frame: np.ndarray, xyxy: np.ndarray) -> np.ndarray | None:
    x1, y1, x2, y2 = [int(v) for v in xyxy]
    tw, th = x2 - x1, y2 - y1
    if tw < 6 or th < 12:
        return None
    cx1 = x1 + tw // 4
    cx2 = x2 - tw // 4
    cy1 = y1 + th // 5
    cy2 = y1 + th // 2
    crop = frame[max(0, cy1) : max(0, cy2), max(0, cx1) : max(0, cx2)]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]
    mask = (sat > 35) & (val > 35) & (val < 245)
    if int(mask.sum()) < 16:
        return None
    return hsv[mask].mean(axis=0).astype(np.float32)


def _detect_boxes(model: Any, frame: np.ndarray, conf: float) -> tuple[list[np.ndarray], tuple[float, float] | None]:
    results = model.predict(frame, verbose=False, conf=conf, classes=[_PERSON, _SPORTS_BALL])
    people: list[np.ndarray] = []
    ball: tuple[float, float] | None = None
    best = 0.0
    if not results:
        return people, ball
    boxes = results[0].boxes
    if boxes is None:
        return people, ball
    xyxy = boxes.xyxy.cpu().numpy()
    cls = boxes.cls.cpu().numpy().astype(int)
    cfs = boxes.conf.cpu().numpy()
    for box, c, cf in zip(xyxy, cls, cfs):
        if int(c) == _PERSON:
            people.append(box.astype(np.float32))
        elif int(c) == _SPORTS_BALL and float(cf) > best:
            best = float(cf)
            ball = (float((box[0] + box[2]) / 2), float((box[1] + box[3]) / 2))
    return people, ball


def _fit_clusters(features: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Return (centers HxS, labels) for 2 kit clusters, or None."""
    if features.shape[0] < 8:
        return None
    # Cluster on Hue + Saturation (ignore value — lighting).
    samples = features[:, :2].astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
    _compact, labels, centers = cv2.kmeans(
        samples, 2, None, criteria, 8, cv2.KMEANS_PP_CENTERS
    )
    return centers, labels.reshape(-1)


def _assign_cluster(centers: np.ndarray, hsv: np.ndarray) -> int:
    hs = hsv[:2]
    d0 = float(np.linalg.norm(hs - centers[0]))
    d1 = float(np.linalg.norm(hs - centers[1]))
    return 0 if d0 <= d1 else 1


def _motion_ball_proxy(
    gray_blur: np.ndarray, prev_gray: np.ndarray | None
) -> tuple[float, float] | None:
    """Lightweight motion blob when YOLO misses the sports ball class."""
    if prev_gray is None:
        return None
    diff = cv2.absdiff(gray_blur, prev_gray)
    _, thr = cv2.threshold(diff, 22, 255, cv2.THRESH_BINARY)
    thr = cv2.morphologyEx(thr, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = 0.0
    h, w = gray_blur.shape
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < 6 or area > (h * w) * 0.012:
            continue
        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw / max(bh, 1)
        if aspect < 0.35 or aspect > 2.8:
            continue
        cx, cy = x + bw / 2.0, y + bh / 2.0
        score = area
        if score > best_score:
            best_score = score
            best = (float(cx), float(cy))
    return best


def _nearest_person(
    people: list[np.ndarray], ball: tuple[float, float]
) -> tuple[int, np.ndarray] | None:
    bx, by = ball
    best_i = None
    best_d = None
    for i, box in enumerate(people):
        cx = float((box[0] + box[2]) / 2)
        cy = float(box[1] + (box[3] - box[1]) * 0.65)
        d = (cx - bx) ** 2 + (cy - by) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best_i = i
    if best_i is None:
        return None
    return best_i, people[best_i]


def run_team_tracking(
    video_path: Path,
    *,
    config: TrackingConfig | None = None,
    anchored_goals: list[dict[str, Any]] | None = None,
    on_progress: ProgressCb | None = None,
    should_cancel: CancelCb | None = None,
) -> dict[str, Any]:
    """Run Phase-3 tracking. Returns possession + timeline + cluster mapping."""
    cfg = config or TrackingConfig()
    model = get_yolo_model()
    if model is None:
        raise RuntimeError(f"YOLO unavailable: {yolo_status()}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    full_duration = frame_count / src_fps if frame_count > 0 else cfg.max_duration_sec
    start_sec = max(0.0, float(cfg.start_sec or 0.0))
    end_sec = min(full_duration, start_sec + cfg.max_duration_sec)
    duration = end_sec  # absolute end time on the match clock
    frame_step = max(int(round(src_fps / cfg.sample_fps)), 1)
    start_frame = int(start_sec * src_fps)

    started = time.time()
    try:
        # ---- Pass 1: collect torso colours ----
        features: list[np.ndarray] = []
        window = max(end_sec - start_sec, 1.0)
        fit_every = max(
            frame_step * max(1, int((window * cfg.sample_fps) / max(cfg.fit_samples, 1))),
            frame_step,
        )
        if start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        frame_idx = start_frame
        while True:
            if should_cancel and should_cancel():
                raise InterruptedError("cancelled")
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / src_fps
            if t > end_sec:
                break
            if frame_idx % fit_every != 0:
                frame_idx += 1
                continue
            small = cv2.resize(frame, (0, 0), fx=cfg.resize_fx, fy=cfg.resize_fx)
            people, _ball = _detect_boxes(model, small, cfg.conf)
            for box in people:
                hsv = _torso_hsv(small, box)
                if hsv is not None:
                    features.append(hsv)
            if on_progress and len(features) % 40 == 0:
                on_progress(
                    {
                        "stage": "fit_kits",
                        "pct": min(25, int(25 * (t - start_sec) / window)),
                        "time_sec": t,
                        "duration_sec": end_sec,
                        "features": len(features),
                    }
                )
            frame_idx += 1
            if len(features) >= cfg.fit_samples * 8:
                break

        feat_arr = np.array(features, dtype=np.float32) if features else np.zeros((0, 3), np.float32)
        fitted = _fit_clusters(feat_arr)
        if fitted is None:
            raise RuntimeError(
                f"Not enough kit colour samples to fit teams (got {len(features)}). "
                "Try a clearer broadcast or higher sample rate."
            )
        centers, _labels = fitted

        # ---- Pass 2: possession timeline ----
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        timeline: list[dict[str, Any]] = []
        poss_votes = {0: 0, 1: 0, None: 0}
        frame_idx = start_frame
        prev_gray = None
        while True:
            if should_cancel and should_cancel():
                raise InterruptedError("cancelled")
            ok, frame = cap.read()
            if not ok:
                break
            t = frame_idx / src_fps
            if t > end_sec:
                break
            if frame_idx % frame_step != 0:
                frame_idx += 1
                continue

            small = cv2.resize(frame, (0, 0), fx=cfg.resize_fx, fy=cfg.resize_fx)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            gray_blur = cv2.GaussianBlur(gray, (5, 5), 0)
            people, ball = _detect_boxes(model, small, cfg.conf)
            if ball is None:
                ball = _motion_ball_proxy(gray_blur, prev_gray)
            prev_gray = gray_blur
            cluster_counts = {0: 0, 1: 0}
            handler_cluster: int | None = None
            for box in people:
                hsv = _torso_hsv(small, box)
                if hsv is None:
                    continue
                cid = _assign_cluster(centers, hsv)
                cluster_counts[cid] += 1
            if ball is not None and people:
                near = _nearest_person(people, ball)
                if near is not None:
                    _i, box = near
                    hsv = _torso_hsv(small, box)
                    if hsv is not None:
                        handler_cluster = _assign_cluster(centers, hsv)
            # Fallback: majority kit on frame when ball/handler colour fails.
            if handler_cluster is None:
                total_p = cluster_counts[0] + cluster_counts[1]
                if total_p >= 4:
                    maj = 0 if cluster_counts[0] >= cluster_counts[1] else 1
                    if max(cluster_counts.values()) / total_p >= 0.55:
                        handler_cluster = maj
            poss_votes[handler_cluster] += 1
            timeline.append(
                {
                    "time_sec": round(t, 3),
                    "cluster": handler_cluster,
                    "people_c0": cluster_counts[0],
                    "people_c1": cluster_counts[1],
                    "ball": bool(ball),
                }
            )
            if on_progress and (len(timeline) % 20 == 0):
                pct = 25 + int(70 * (t - start_sec) / window)
                on_progress(
                    {
                        "stage": "possession",
                        "pct": min(95, pct),
                        "time_sec": t,
                        "duration_sec": end_sec,
                        "samples": len(timeline),
                    }
                )
            frame_idx += 1
    finally:
        cap.release()

    # Map clusters → home/away via anchored goals.
    cluster_to_side = _map_clusters_to_sides(
        video_path,
        centers,
        anchored_goals or [],
        model=model,
        conf=cfg.conf,
        resize_fx=cfg.resize_fx,
    )

    def side_of(cluster: int | None) -> str | None:
        if cluster is None:
            return None
        return cluster_to_side.get(int(cluster))

    home_frames = 0
    away_frames = 0
    unknown_frames = 0
    for row in timeline:
        side = side_of(row.get("cluster"))
        row["team"] = side
        if side == "home":
            home_frames += 1
        elif side == "away":
            away_frames += 1
        else:
            unknown_frames += 1

    known = home_frames + away_frames
    if known <= 0:
        home_pct = None
        away_pct = None
    else:
        home_pct = round(100.0 * home_frames / known, 1)
        away_pct = round(100.0 - home_pct, 1)

    return {
        "phase": "match-pack-phase3",
        "method": "yolo-kit-kmeans-possession-v1",
        "detector": yolo_status(),
        "config": {
            "sample_fps": cfg.sample_fps,
            "resize_fx": cfg.resize_fx,
            "max_duration_sec": cfg.max_duration_sec,
        },
        "duration_sec": end_sec - start_sec,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "elapsed_sec": round(time.time() - started, 1),
        "kit_centers_hs": centers.tolist(),
        "cluster_to_side": {str(k): v for k, v in cluster_to_side.items() if k != "_source"},
        "mapping_source": cluster_to_side.get("_source", "fallback"),
        "samples": len(timeline),
        "possession": {
            "home_pct": home_pct,
            "away_pct": away_pct,
            "home_frames": home_frames,
            "away_frames": away_frames,
            "unknown_frames": unknown_frames,
            "known_frames": known,
        },
        "timeline": timeline,
        "warning": (
            "Approximate broadcast tracking: two kit clusters + nearest ball handler "
            "(motion ball proxy + majority-kit fallback). Referees/keepers/ads can confuse "
            "colours. Possession ignores unknown frames. Not Opta/StatsBomb grade."
        ),
    }


def _map_clusters_to_sides(
    video_path: Path,
    centers: np.ndarray,
    anchored_goals: list[dict[str, Any]],
    *,
    model: Any,
    conf: float,
    resize_fx: float,
) -> dict[Any, Any]:
    """Vote with anchored goal moments: handler cluster → fact team."""
    votes = {0: {"home": 0, "away": 0}, 1: {"home": 0, "away": 0}}
    cap = cv2.VideoCapture(str(video_path))
    try:
        for g in anchored_goals:
            if not g.get("matched") or g.get("film_time_sec") is None:
                continue
            team = g.get("team")
            if team not in {"home", "away"}:
                continue
            t = float(g["film_time_sec"])
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            small = cv2.resize(frame, (0, 0), fx=resize_fx, fy=resize_fx)
            people, ball = _detect_boxes(model, small, conf)
            cid = None
            if people and ball is not None:
                near = _nearest_person(people, ball)
                if near is not None:
                    _i, box = near
                    hsv = _torso_hsv(small, box)
                    if hsv is not None:
                        cid = _assign_cluster(centers, hsv)
            if cid is None and people:
                # Majority kit in the goal frame → scoring team vote.
                counts = {0: 0, 1: 0}
                for box in people:
                    hsv = _torso_hsv(small, box)
                    if hsv is None:
                        continue
                    counts[_assign_cluster(centers, hsv)] += 1
                if counts[0] + counts[1] >= 3:
                    cid = 0 if counts[0] >= counts[1] else 1
            if cid is None:
                continue
            votes[cid][team] += 1
    finally:
        cap.release()

    # Choose assignment maximizing correct votes.
    # Option A: c0=home, c1=away
    score_a = votes[0]["home"] + votes[1]["away"]
    score_b = votes[0]["away"] + votes[1]["home"]
    if score_a == 0 and score_b == 0:
        # Fallback: cluster with more saturated / blue-ish hue → home is arbitrary.
        return {0: "home", 1: "away", "_source": "fallback_order"}
    if score_a >= score_b:
        return {0: "home", 1: "away", "_source": "anchored_goals"}
    return {0: "away", 1: "home", "_source": "anchored_goals"}


# Min seconds between accepted tags of the same class. The spotter fires many
# near-duplicate Shot/Cross labels; without this the team board is unusable.
DEFAULT_DEBOUNCE_GAPS: dict[str, float] = {
    "Shot": 30.0,
    "Goal": 45.0,
    "Cross": 12.0,
    "Pass": 5.0,
    "High Pass": 8.0,
    "Drive": 10.0,
    "Header": 12.0,
    "Throw In": 15.0,
    "Free Kick": 20.0,
    "Player Successful Tackle": 8.0,
    "Out": 6.0,
    "Ball Player Block": 8.0,
}


def debounce_film_events(
    film_events: list[dict[str, Any]],
    gaps: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Drop near-duplicate film tags (same label within a gap)."""
    rules = gaps or DEFAULT_DEBOUNCE_GAPS
    last: dict[str, float] = {}
    out: list[dict[str, Any]] = []
    for e in sorted(film_events, key=lambda x: float(x.get("time_sec") or 0)):
        lab = e.get("label") or "Unknown"
        t = float(e.get("time_sec") or 0)
        gap = rules.get(lab)
        if gap is not None and lab in last and (t - last[lab]) < gap:
            continue
        last[lab] = t
        out.append(e)
    return out


def assign_events_to_teams(
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    debounce: bool = True,
    gaps: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Assign each film event to home/away using nearest possession sample."""
    if not timeline:
        return {"home": {}, "away": {}, "unknown": {}, "events_tagged": 0}

    source_events = debounce_film_events(film_events, gaps) if debounce else list(film_events)

    times = np.array([row["time_sec"] for row in timeline], dtype=np.float64)
    teams = [row.get("team") for row in timeline]

    def team_at(t: float) -> str | None:
        i = int(np.argmin(np.abs(times - t)))
        # Only trust if within 8s of a sample.
        if abs(times[i] - t) > 8.0:
            return None
        return teams[i]

    from collections import Counter

    home_c: Counter[str] = Counter()
    away_c: Counter[str] = Counter()
    unk_c: Counter[str] = Counter()
    tagged = 0
    for e in source_events:
        label = e.get("label") or "Unknown"
        side = team_at(float(e.get("time_sec") or 0))
        if side == "home":
            home_c[label] += 1
            tagged += 1
        elif side == "away":
            away_c[label] += 1
            tagged += 1
        else:
            unk_c[label] += 1

    def pack(c: Counter[str]) -> dict[str, Any]:
        # Shots: Shot tags only (Goal tags are noisy; fact goals stay in facts).
        shot_tags = int(c.get("Shot", 0))
        passes = int(
            c.get("Pass", 0)
            + c.get("High Pass", 0)
            + c.get("Cross", 0)
            + c.get("Throw In", 0)
            + c.get("Free Kick", 0)
        )
        return {
            # Kept for panel / debugging — not trusted as Opta shots.
            "shot_tags": shot_tags,
            "shots": shot_tags,
            "passes": passes,
            "crosses": int(c.get("Cross", 0)),
            "tackles": int(c.get("Player Successful Tackle", 0)),
            "headers": int(c.get("Header", 0)),
            "drives": int(c.get("Drive", 0)),
            "throw_ins": int(c.get("Throw In", 0)),
            "labels": dict(c),
        }

    return {
        "home": pack(home_c),
        "away": pack(away_c),
        "unknown": pack(unk_c),
        "events_tagged": tagged,
        "events_total": len(film_events),
        "events_after_debounce": len(source_events),
        "debounced": bool(debounce),
        # Board policy: film shot tags stay off the StatsBomb-shaped Shots row.
        "shots_on_board": False,
        "shots_note": (
            "Film Shot tags remain far above true shot counts even after debouncing; "
            "team-board Shots stay blank until a dedicated shot model. See shot_tags."
        ),
    }
