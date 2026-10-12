"""Aggregate approximate video events into a StatMan-shaped stats payload."""

from __future__ import annotations

from collections import Counter
from typing import Any


def stats_from_video_events(
    *,
    job_id: str,
    probe: dict[str, Any],
    events: list[dict[str, Any]],
    detector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = Counter(e["label"] for e in events)
    passes = (
        counts["Pass"]
        + counts["High Pass"]
        + counts["Cross"]
        + counts["Throw In"]
        + counts["Free Kick"]
    )
    shots = counts["Shot"] + counts["Goal"]
    tackles = counts["Player Successful Tackle"]
    blocks = counts["Ball Player Block"]
    headers = counts["Header"]
    drives = counts["Drive"]
    outs = counts["Out"]
    goals = counts["Goal"]

    # Video pipeline does not identify teams or true possession chains.
    duration = float(probe.get("duration_sec") or 0.0)
    per90 = (90.0 / duration) if duration > 1 else None
    backends = {e.get("detector") for e in events if e.get("detector")}
    if detector and detector.get("backend"):
        backends.add(detector["backend"])
    method = "yolo-person-ball-spotter-v1" if "yolo" in backends else "opencv-hog-motion-spotter-v0"

    def rate(n: int) -> float | None:
        if per90 is None:
            return None
        return round(n * per90, 2)

    return {
        "source": {
            "provider": "uploaded-video",
            "quality": "approximate",
            "approximate": True,
            "method": method,
            "detector": detector or {"backend": "opencv-hog"},
            "taxonomy": "SoccerNet Ball Action Spotting (12 classes)",
            "warning": (
                "This is approximate. Full-match video spotting is not Opta/StatsBomb "
                "event data — do not trust these counts. xG, PPDA, pass accuracy, "
                "progressive passes, and aerial duels are not provider-grade. "
                "Team identity is not resolved from the broadcast alone. "
                "For real match stats, import StatsBomb/Opta JSON via /import."
            ),
            "job_id": job_id,
            "scope": "full_match",
        },
        "definitions": {
            "events": (
                "SoccerNet-style ball actions spotted across the full match "
                "(default sample 0.5 fps, up to 150 minutes)."
            ),
            "passes": "Sum of Pass + High Pass + Cross + Throw In + Free Kick tags.",
            "shots": "Sum of Shot + Goal tags.",
            "tackles": "Player Successful Tackle tags only (no lost tackles).",
            "headers": "Header tags (not the same as aerial duels won/lost).",
            "xg": "Not estimated from video in v0.",
            "ppda": "Not estimated from video in v0 (needs team identity + pass/def split).",
            "possession_pct": "Not estimated from video in v0.",
            "progressive_passes": "Not estimated from video in v0 (needs pitch coordinates).",
            "pass_accuracy": "Not estimated from video in v0 (no success/fail labels).",
        },
        "match": {
            "job_id": job_id,
            "filename": probe.get("filename"),
            "duration_sec": probe.get("duration_sec"),
            "duration_min": (
                round(float(probe["duration_sec"]) / 60.0, 1)
                if probe.get("duration_sec")
                else None
            ),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "fps": probe.get("fps"),
            "scope": "full_match",
        },
        "totals": {
            "events": len(events),
            "goals": goals,
            "shots": shots,
            "passes": passes,
            "drives": drives,
            "headers": headers,
            "tackles": tackles,
            "blocks": blocks,
            "outs": outs,
            "crosses": counts["Cross"],
            "high_passes": counts["High Pass"],
            "throw_ins": counts["Throw In"],
            "free_kicks": counts["Free Kick"],
            "xg": None,
            "ppda": None,
            "possession_pct": None,
            "pass_accuracy": None,
            "progressive_passes": None,
            "aerials_won": None,
            "aerials_lost": None,
            "interceptions": None,
            "clearances": None,
        },
        "per_90": {
            "shots": rate(shots),
            "passes": rate(passes),
            "tackles": rate(tackles),
            "headers": rate(headers),
            "drives": rate(drives),
        },
        "label_counts": {k: int(counts.get(k, 0)) for k in (
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
        )},
        "timeline": events[:500],
    }
