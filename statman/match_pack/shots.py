"""Phase 4: rescore film Shot tags into approximate true shot counts.

Film spotting labels almost anything near a goal line as Shot. This module
re-scores candidates with short video windows (ball motion toward a goal line),
selects a rate-limited top-K set, and always includes fact goals as shots on target.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from statman.match_pack import store
from statman.video.detector import get_yolo_model, yolo_status

PHASE = "match-pack-phase4"
ProgressCb = Callable[[dict[str, Any]], None]

# Typical full-match shot volume for a low-scoring game; used as a soft ceiling.
DEFAULT_MAX_SHOTS_PER_90 = 16.0
DEFAULT_MIN_GAP_SEC = 45.0
DEFAULT_REFRAME_GAP_SEC = 8.0  # pre-filter before expensive seeks


def _team_at(timeline: list[dict[str, Any]], t: float) -> str | None:
    if not timeline:
        return None
    times = np.array([row["time_sec"] for row in timeline], dtype=np.float64)
    i = int(np.argmin(np.abs(times - t)))
    if abs(float(times[i]) - t) > 8.0:
        return None
    side = timeline[i].get("team")
    return side if side in {"home", "away"} else None


def _detect_ball_xy(
    model: Any, frame_bgr: np.ndarray, *, resize_fx: float = 0.4
) -> tuple[float, float] | None:
    small = cv2.resize(frame_bgr, (0, 0), fx=resize_fx, fy=resize_fx)
    results = model.predict(small, verbose=False, conf=0.2, classes=[32])
    if not results or results[0].boxes is None or len(results[0].boxes) == 0:
        return None
    boxes = results[0].boxes
    conf = boxes.conf.cpu().numpy()
    xyxy = boxes.xyxy.cpu().numpy()
    i = int(np.argmax(conf))
    x1, y1, x2, y2 = xyxy[i]
    return (float((x1 + x2) / 2) / resize_fx, float((y1 + y2) / 2) / resize_fx)


def _score_kinematics(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    frame_w: float,
    frame_h: float,
    motion: float,
) -> dict[str, Any]:
    dx, dy = x2 - x1, y2 - y1
    speed = float(np.hypot(dx, dy))
    dist_top = min(y1, y2)
    dist_bot = min(frame_h - y1, frame_h - y2)
    if dist_top <= dist_bot:
        toward = max(0.0, -dy)
        goal_dist = dist_top
        end = "top"
    else:
        toward = max(0.0, dy)
        goal_dist = dist_bot
        end = "bottom"
    prox = 1.0 - min(goal_dist / (0.32 * frame_h), 1.0)
    toward_n = min(toward / (0.14 * frame_h), 1.0) if toward > 0 else 0.0
    speed_n = min(speed / (0.2 * frame_h), 1.0)
    motion_n = min(float(motion) / 24.0, 1.0)
    score = 0.35 * prox + 0.35 * toward_n + 0.2 * speed_n + 0.1 * motion_n
    if toward_n <= 0:
        score *= 0.45
    if goal_dist > 0.35 * frame_h:
        score *= 0.5
    return {
        "score": round(float(score), 3),
        "toward": float(toward),
        "goal_dist": float(goal_dist),
        "speed": float(speed),
        "end": end,
        "prox": float(prox),
        "toward_n": float(toward_n),
    }


def score_shot_candidates(
    video_path: Path,
    film_events: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    *,
    on_progress: ProgressCb | None = None,
) -> list[dict[str, Any]]:
    """Rescore film Shot tags with a short ball-track window around each tag."""
    model = get_yolo_model()
    if model is None:
        raise RuntimeError(f"YOLO unavailable: {yolo_status()}")

    shots = sorted(
        [e for e in film_events if e.get("label") == "Shot" and e.get("ball_xy")],
        key=lambda e: float(e.get("time_sec") or 0),
    )
    # Cheap temporal pre-filter before seeks.
    cands: list[dict[str, Any]] = []
    last = -1e9
    for e in shots:
        t = float(e["time_sec"])
        if t - last < DEFAULT_REFRAME_GAP_SEC:
            continue
        cands.append(e)
        last = t

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    frame_w = float(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
    frame_h = float(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)

    scored: list[dict[str, Any]] = []
    try:
        for i, e in enumerate(cands):
            t = float(e["time_sec"])
            balls: list[tuple[float, float]] = []
            for dt in (-0.45, 0.0, 0.45):
                cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t + dt) * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    continue
                b = _detect_ball_xy(model, frame)
                if b is not None:
                    balls.append(b)
            if len(balls) < 2:
                # Fall back to handler → ball from the film tag.
                if e.get("handler_xy") and e.get("ball_xy"):
                    balls = [tuple(e["handler_xy"]), tuple(e["ball_xy"])]  # type: ignore[list-item]
                else:
                    continue
            kin = _score_kinematics(
                balls[0][0],
                balls[0][1],
                balls[-1][0],
                balls[-1][1],
                frame_w=frame_w,
                frame_h=frame_h,
                motion=float(e.get("motion") or 0),
            )
            scored.append(
                {
                    "time_sec": t,
                    "minute": round(t / 60.0, 2),
                    "team": _team_at(timeline, t),
                    "label": "Shot",
                    "confidence": e.get("confidence"),
                    "film_motion": e.get("motion"),
                    "source": "rescored_film_shot",
                    **kin,
                }
            )
            if on_progress and (i % 10 == 0 or i + 1 == len(cands)):
                on_progress(
                    {
                        "stage": "score_shots",
                        "pct": int(95 * (i + 1) / max(len(cands), 1)),
                        "done": i + 1,
                        "total": len(cands),
                    }
                )
    finally:
        cap.release()
    return scored


def select_shots(
    scored: list[dict[str, Any]],
    *,
    duration_sec: float,
    fact_goals: list[dict[str, Any]],
    max_shots_per_90: float = DEFAULT_MAX_SHOTS_PER_90,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    min_score: float = 0.55,
) -> dict[str, Any]:
    """Pick a rate-limited shot list; always include fact goals as SoT."""
    budget = max(6, int(round(max_shots_per_90 * float(duration_sec) / 5400.0)))
    pool = sorted(
        [e for e in scored if float(e.get("score") or 0) >= min_score and e.get("team") in {"home", "away"}],
        key=lambda e: (-float(e["score"]), float(e["time_sec"])),
    )
    chosen: list[dict[str, Any]] = []
    for e in pool:
        if any(abs(float(e["time_sec"]) - float(o["time_sec"])) < min_gap_sec for o in chosen):
            continue
        row = dict(e)
        # SoT from video alone is still unreliable — default off; fact goals mark SoT.
        row["on_target"] = False
        chosen.append(row)
        if len(chosen) >= budget:
            break
    chosen.sort(key=lambda e: float(e["time_sec"]))

    # Fact goals → guaranteed shot + SoT for that team (authoritative).
    goal_rows: list[dict[str, Any]] = []
    for g in fact_goals:
        team = g.get("team")
        if team not in {"home", "away"}:
            continue
        minute = g.get("fact_minute", g.get("minute"))
        t = float(g.get("film_time_sec") or (float(minute or 0) * 60.0))
        # If a chosen shot is already near this goal, mark it SoT / goal-linked.
        linked = False
        for row in chosen:
            if row.get("team") == team and abs(float(row["time_sec"]) - t) <= 90:
                row["on_target"] = True
                row["fact_goal"] = True
                row["player_name"] = g.get("player_name")
                linked = True
                break
        if not linked:
            goal_rows.append(
                {
                    "time_sec": t,
                    "minute": float(minute) if minute is not None else round(t / 60.0, 2),
                    "team": team,
                    "label": "Shot",
                    "score": 1.0,
                    "on_target": True,
                    "fact_goal": True,
                    "player_name": g.get("player_name"),
                    "assist_name": g.get("assist_name"),
                    "source": "fact_goal",
                }
            )
    all_shots = sorted(chosen + goal_rows, key=lambda e: float(e["time_sec"]))

    def _count(side: str) -> dict[str, int]:
        rows = [e for e in all_shots if e.get("team") == side]
        return {
            "shots": len(rows),
            "shots_on_target": sum(1 for e in rows if e.get("on_target")),
        }

    return {
        "phase": PHASE,
        "method": "yolo-shot-rescore-topk-v1",
        "budget": budget,
        "min_gap_sec": min_gap_sec,
        "min_score": min_score,
        "candidates_scored": len(scored),
        "selected": all_shots,
        "totals": {
            "home": _count("home"),
            "away": _count("away"),
            "match": {
                "shots": len(all_shots),
                "shots_on_target": sum(1 for e in all_shots if e.get("on_target")),
            },
        },
        "warning": (
            "Approximate shot list: film Shot tags re-scored with ball motion toward a "
            "goal line, then rate-limited. SoT currently follows fact goals only "
            "(video SoT still too noisy). Not Opta."
        ),
    }


def merge_shots_into_sheet(sheet: dict[str, Any], shot_result: dict[str, Any]) -> dict[str, Any]:
    """Write Phase-4 shots / SoT onto the team board."""
    out = dict(sheet)
    totals = (shot_result or {}).get("totals") or {}
    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        side_tot = totals.get(side) or {}
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        attack = dict(sections.get("attack") or {})

        shots = side_tot.get("shots")
        sot = side_tot.get("shots_on_target")
        if shots is not None:
            t["shots"] = int(shots)
            attack["shots"] = int(shots)
            prov["shots"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "rescored film shots (top-K toward goal) + fact goals",
            }
        if sot is not None:
            t["shots_on_target"] = int(sot)
            attack["shots_on_target"] = int(sot)
            if shots and shots > 0:
                t["shot_accuracy"] = round(100.0 * float(sot) / float(shots), 1)
                attack["shot_accuracy"] = t["shot_accuracy"]
            prov["shots_on_target"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "SoT ≈ high-score near-goal shots + fact goals",
            }

        sections["attack"] = attack
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams
    out["shots"] = {
        "phase": PHASE,
        "method": shot_result.get("method"),
        "totals": totals,
        "selected": shot_result.get("selected") or [],
        "budget": shot_result.get("budget"),
        "warning": shot_result.get("warning"),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    pending = [f for f in (cov.get("pending_later_phases") or []) if f != "shots"]
    approx = sorted(set(cov.get("approximate_video") or []) | {"shots", "shots_on_target"})
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    phase3 = dict(cov.get("phase3") or {})
    phase3["shots_on_board"] = True
    phase3["shots_home"] = (totals.get("home") or {}).get("shots")
    phase3["shots_away"] = (totals.get("away") or {}).get("shots")
    phase3["sot_home"] = (totals.get("home") or {}).get("shots_on_target")
    phase3["sot_away"] = (totals.get("away") or {}).get("shots_on_target")
    cov["phase3"] = phase3
    cov["phase4"] = {
        "shots_home": (totals.get("home") or {}).get("shots"),
        "shots_away": (totals.get("away") or {}).get("shots"),
        "sot_home": (totals.get("home") or {}).get("shots_on_target"),
        "sot_away": (totals.get("away") or {}).get("shots_on_target"),
        "selected": len(shot_result.get("selected") or []),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film_plus_tracking_plus_shots"
    note = (src.get("note") or "").rstrip()
    src["note"] = (
        f"{note} Phase 4: approximate shots/SoT from rescored film tags + fact goals."
    ).strip()
    out["source"] = src
    return out


def run_phase4(
    pack_id: str,
    *,
    max_shots_per_90: float = DEFAULT_MAX_SHOTS_PER_90,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Score shots for a pack and merge onto the sheet."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    path = Path(video.get("path") or "")
    if not path.exists():
        raise ValueError("Pack video missing")
    events_path = store.pack_dir(pack_id) / "film_events.json"
    tracking_path = store.pack_dir(pack_id) / "tracking.json"
    if not events_path.exists():
        raise ValueError("Run Phase 2 film analyze first")
    if not tracking_path.exists():
        raise ValueError("Run Phase 3 tracking first (needed for home/away)")

    film_events = json.loads(events_path.read_text(encoding="utf-8"))
    tracking = json.loads(tracking_path.read_text(encoding="utf-8"))
    timeline = tracking.get("timeline") or []

    facts = meta.get("facts") or {}
    fact_goals = []
    if isinstance(facts.get("film_corrected"), dict):
        fact_goals = list(facts["film_corrected"].get("anchored_goals") or [])
    if not fact_goals:
        fact_goals = [
            {
                "team": e.get("team"),
                "fact_minute": e.get("minute"),
                "minute": e.get("minute"),
                "player_name": e.get("player_name"),
                "assist_name": e.get("assist_name"),
                "film_time_sec": float(e.get("minute") or 0) * 60.0,
            }
            for e in (facts.get("events") or [])
            if e.get("type") == "goal"
        ]

    meta["phase4"] = {
        "status": "running",
        "progress": {"stage": "score_shots", "pct": 1},
        "error": None,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)

    def _prog(payload: dict[str, Any]) -> None:
        cur = store.read_meta(pack_id) or meta
        p4 = dict(cur.get("phase4") or {})
        p4["status"] = "running"
        p4["progress"] = payload
        p4["updated_at"] = time.time()
        cur["phase4"] = p4
        store.write_meta(pack_id, cur)
        if on_progress:
            on_progress(payload)

    try:
        scored = score_shot_candidates(path, film_events, timeline, on_progress=_prog)
        duration = float(
            (tracking.get("end_sec") or 0)
            or (tracking.get("duration_sec") or 0)
            or (meta.get("video") or {}).get("duration_sec")
            or 90 * 60
        )
        if duration < 60:
            duration = 90 * 60
        result = select_shots(
            scored,
            duration_sec=duration,
            fact_goals=fact_goals,
            max_shots_per_90=max_shots_per_90,
            min_gap_sec=min_gap_sec,
        )
        result["detector"] = yolo_status()
        result["created_at"] = time.time()
        shots_path = store.pack_dir(pack_id) / "shots.json"
        shots_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

        # Rebuild sheet from facts + film + tracking + shots.
        from statman.match_pack.phase3 import apply_phase3_to_sheet

        meta = apply_phase3_to_sheet(pack_id)
        sheet = meta.get("sheet") or {}
        sheet = merge_shots_into_sheet(sheet, result)
        sheet_path = store.pack_dir(pack_id) / "sheet.json"
        sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
        meta["sheet"] = sheet
        meta["sheet_path"] = str(sheet_path)
        meta["shots_path"] = str(shots_path)
        meta["status"] = "phase4_ready"
        meta["phase"] = PHASE
        meta["coverage"] = sheet["source"]["coverage"]
        meta["phase4"] = {
            "status": "done",
            "progress": {"stage": "done", "pct": 100},
            "totals": result.get("totals"),
            "selected": len(result.get("selected") or []),
            "budget": result.get("budget"),
            "error": None,
            "updated_at": time.time(),
        }
        store.write_meta(pack_id, meta)
        return meta
    except Exception as exc:  # noqa: BLE001
        cur = store.read_meta(pack_id) or meta
        cur["phase4"] = {
            "status": "error",
            "error": str(exc),
            "progress": {"stage": "error", "pct": 0},
            "updated_at": time.time(),
        }
        store.write_meta(pack_id, cur)
        raise
