"""Probe helpers for uploaded full-match videos."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import cv2


def probe_video(path: Path) -> dict[str, Any]:
    """Return duration, fps, size, and stream info for a video file.

    Prefers OpenCV so we do not depend on ffprobe's shared libraries (which can
    segfault under some tmux ``LD_LIBRARY_PATH`` setups).
    """
    info = _probe_opencv(path)
    if info.get("duration_sec"):
        return info
    try:
        return _probe_ffprobe(path)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return info


def _probe_opencv(path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or None
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = (frame_count / fps) if fps and frame_count > 0 else 0.0
    cap.release()
    return {
        "path": str(path),
        "filename": path.name,
        "duration_sec": round(duration, 3),
        "size_bytes": path.stat().st_size,
        "width": width,
        "height": height,
        "fps": round(fps, 3) if fps else None,
        "codec": None,
        "probe_backend": "opencv",
    }


def _probe_ffprobe(path: Path) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    raw = subprocess.check_output(cmd, text=True, env=env)
    data = json.loads(raw)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    fmt = data.get("format", {})
    fps = _parse_fps(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0.0)
    return {
        "path": str(path),
        "filename": path.name,
        "duration_sec": round(duration, 3),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "width": int(video_stream.get("width") or 0),
        "height": int(video_stream.get("height") or 0),
        "fps": fps,
        "codec": video_stream.get("codec_name"),
        "probe_backend": "ffprobe",
    }


def _parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            if den_f == 0:
                return None
            return round(float(num) / den_f, 3)
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None
