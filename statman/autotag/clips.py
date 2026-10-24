"""Plan and cut overlapping clips from a match video (ffmpeg).

A clip records both its video offset and its match-clock offset so tagger
times can be mapped back to the match clock. ``segments`` maps video time to
match time, e.g. a second half that starts at video 3120 s but match 2700 s::

    [{"video_start": 0, "match_start": 0}, {"video_start": 3120, "match_start": 2700}]
"""

from __future__ import annotations

import math
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from statman.persistence.paths import configured_video_dir

DEFAULT_CLIP_SECONDS = 15.0
DEFAULT_OVERLAP_SECONDS = 5.0


@dataclass(frozen=True)
class Clip:
    index: int
    video_start: float
    video_end: float
    match_start: float
    period: int
    path: str | None = None

    @property
    def duration(self) -> float:
        return round(self.video_end - self.video_start, 3)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "duration": self.duration}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Clip":
        return cls(
            index=int(d["index"]),
            video_start=float(d["video_start"]),
            video_end=float(d["video_end"]),
            match_start=float(d["match_start"]),
            period=int(d.get("period") or 1),
            path=d.get("path"),
        )


def _norm_segments(segments: list[dict[str, Any]] | None) -> list[dict[str, float]]:
    segs = sorted(
        ({"video_start": float(s["video_start"]), "match_start": float(s["match_start"])} for s in (segments or [])),
        key=lambda s: s["video_start"],
    )
    if not segs or segs[0]["video_start"] > 0:
        # Before the first segment the match clock runs from video 0 unless told otherwise.
        segs.insert(0, {"video_start": 0.0, "match_start": 0.0} if not segs else {
            "video_start": 0.0, "match_start": segs[0]["match_start"] - segs[0]["video_start"]})
    return segs


def video_to_match(t_video: float, segments: list[dict[str, Any]] | None = None) -> tuple[float, int]:
    """Map a video timestamp to (match clock seconds, period index starting at 1)."""

    segs = _norm_segments(segments)
    period = 1
    seg = segs[0]
    for i, s in enumerate(segs):
        if t_video >= s["video_start"]:
            seg, period = s, i + 1
    return round(max(0.0, seg["match_start"] + (t_video - seg["video_start"])), 3), period


def plan_clips(
    duration: float,
    *,
    clip_seconds: float = DEFAULT_CLIP_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    segments: list[dict[str, Any]] | None = None,
) -> list[Clip]:
    """Overlapping windows covering [0, duration]. Last clip ends at duration."""

    if duration <= 0:
        return []
    if clip_seconds <= 0 or overlap_seconds < 0 or overlap_seconds >= clip_seconds:
        raise ValueError("need clip_seconds > overlap_seconds >= 0")
    step = clip_seconds - overlap_seconds
    count = max(1, math.ceil(max(0.0, duration - overlap_seconds) / step))
    clips: list[Clip] = []
    for i in range(count):
        start = round(i * step, 3)
        end = round(min(duration, start + clip_seconds), 3)
        if end - start <= 0:
            break
        match_start, period = video_to_match(start, segments)
        clips.append(Clip(i, start, end, match_start, period))
    return clips


def clips_dir(match_id: str) -> Path:
    base = configured_video_dir()
    if base is None:
        from statman.autotag import store

        base = store.ensure_root()
    path = base / "clips" / match_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ffmpeg_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}


def cut_clip(src: Path, clip: Clip, out_dir: Path, *, height: int = 720) -> Clip:
    out = out_dir / f"clip_{clip.index:05d}.mp4"
    if not (out.exists() and out.stat().st_size > 0):
        tmp = out.with_suffix(".part.mp4")
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-ss", f"{clip.video_start:.3f}", "-i", str(src),
            "-t", f"{clip.duration:.3f}",
            "-vf", f"scale=-2:{height}", "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            str(tmp),
        ]
        subprocess.run(cmd, check=True, env=_ffmpeg_env(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        tmp.replace(out)
    return Clip(clip.index, clip.video_start, clip.video_end, clip.match_start, clip.period, str(out))


def extract_frames(clip_path: Path, n_frames: int, duration: float, *, width: int = 1280) -> list[tuple[float, bytes]]:
    """Sample ``n_frames`` evenly spaced JPEG frames: [(t_clip_seconds, jpeg bytes)]."""

    n = max(1, n_frames)
    frames: list[tuple[float, bytes]] = []
    for i in range(n):
        t = round(duration * (i + 0.5) / n, 3)
        cmd = [
            "ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(clip_path),
            "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2", "-c:v", "mjpeg", "pipe:1",
        ]
        proc = subprocess.run(cmd, check=True, env=_ffmpeg_env(), capture_output=True)
        if proc.stdout:
            frames.append((t, proc.stdout))
    return frames
