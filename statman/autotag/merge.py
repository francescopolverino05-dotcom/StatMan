"""Turn per-clip tagger output into one deduplicated match timeline."""

from __future__ import annotations

import math
import os
from typing import Any

from statman.autotag.clips import Clip
from statman.autotag.taxonomy import normalize_event

DEFAULT_REVIEW_THRESHOLD = 0.75
# Same action seen by two overlapping clips lands within this many seconds.
DEDUPE_WINDOW_SECONDS: dict[str, float] = {"default": 2.0, "card": 6.0, "goal": 6.0, "goal_conceded": 6.0, "corner": 4.0}
KEY_PASS_WINDOW_SECONDS = 6.0
# Two overlap copies of one action start within this distance (0-100 pitch units).
DEDUPE_MAX_DISTANCE = 15.0


def review_threshold() -> float:
    raw = os.environ.get("STATMAN_REVIEW_THRESHOLD", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_REVIEW_THRESHOLD
    except ValueError:
        return DEFAULT_REVIEW_THRESHOLD
    return min(max(value, 0.0), 1.0)


def clip_events_to_match(clip: Clip, raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise one clip's events and move them onto the match clock."""

    out: list[dict[str, Any]] = []
    for raw in raw_events:
        raw = dict(raw)
        t_clip = raw.pop("t_clip_seconds", None)
        if t_clip is None and raw.get("t_match_seconds") is None:
            continue
        if t_clip is not None:
            try:
                t_clip = min(max(float(t_clip), 0.0), clip.duration)
            except (TypeError, ValueError):
                continue
            raw["t_match_seconds"] = clip.match_start + t_clip
        else:
            t_clip = float(raw["t_match_seconds"]) - clip.match_start
        event, issues = normalize_event(raw)
        if event is None:
            continue
        event["video_ts_seconds"] = round(clip.video_start + t_clip, 2)
        event["period"] = clip.period
        event["clip_ids"] = [clip.index]
        event["issues"] = issues
        # Distance from clip centre: events near an edge may be cut off.
        event["_edge"] = abs(t_clip - clip.duration / 2) / max(clip.duration / 2, 1e-6)
        out.append(event)
    return out


def _compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["type"] != b["type"] or a["team"] != b["team"]:
        return False
    if a.get("code") and b.get("code") and a["code"] != b["code"]:
        return False  # e.g. PASS vs CROSS
    if None not in (a.get("x"), a.get("y"), b.get("x"), b.get("y")):
        if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) > DEDUPE_MAX_DISTANCE:
            return False
    if a["shirt"] is not None and b["shirt"] is not None and a["shirt"] != b["shirt"]:
        return False
    if a["type"] == "card" and a["attributes"].get("color") != b["attributes"].get("color"):
        return False
    window = DEDUPE_WINDOW_SECONDS.get(a["type"], DEDUPE_WINDOW_SECONDS["default"])
    return abs(a["t_match_seconds"] - b["t_match_seconds"]) <= window


def _better(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """True when ``a`` is the more trustworthy observation of the pair."""
    if a["confidence"] != b["confidence"]:
        return a["confidence"] > b["confidence"]
    return a["_edge"] < b["_edge"]


def dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicates coming from *different* overlapping clips.

    Duplicates = same team + type (+ code when both have one) within the
    type's window (~2 s for on-ball events) and, when both are placed, start
    points closer than ``DEDUPE_MAX_DISTANCE``.

    Two same-type events from the same clip are always kept (two quick passes
    are two passes). The kept copy is the most confident one; it gains the
    other copy's clip ids and any attribute it lacked. Disagreements on an
    attribute are recorded as issues so the event goes to review.
    """

    ordered = sorted(events, key=lambda e: (e["t_match_seconds"], e["clip_ids"][0]))
    merged: list[dict[str, Any]] = []
    for ev in ordered:
        ev = {**ev, "attributes": dict(ev["attributes"]), "issues": list(ev.get("issues") or []), "clip_ids": list(ev["clip_ids"])}
        match = None
        for cand in reversed(merged):
            if ev["t_match_seconds"] - cand["t_match_seconds"] > 10:
                break
            if set(cand["clip_ids"]) & set(ev["clip_ids"]):
                continue
            if _compatible(cand, ev):
                match = cand
                break
        if match is None:
            merged.append(ev)
            continue
        keep, other = (ev, match) if _better(ev, match) else (match, ev)
        for key, value in other["attributes"].items():
            if key not in keep["attributes"]:
                keep["attributes"][key] = value
            elif keep["attributes"][key] != value:
                keep["issues"].append(f"clips disagree on {key}")
        for key in ("shirt", "player", "x", "y", "x2", "y2", "outcome", "code", "detail"):
            if keep.get(key) is None and other.get(key) is not None:
                keep[key] = other[key]
        keep["clip_ids"] = sorted(set(keep["clip_ids"]) | set(other["clip_ids"]))
        keep["issues"] = sorted(
            i for i in set(keep["issues"]) | set(other["issues"])
            if not (i.startswith("missing ") and i[len("missing "):] in keep["attributes"])
        )
        merged[merged.index(match)] = keep
    for ev in merged:
        ev.pop("_edge", None)
    return sorted(merged, key=lambda e: e["t_match_seconds"])


def derive_key_passes(events: list[dict[str, Any]]) -> None:
    """Flag the last completed pass by the shooting team before each shot."""

    ordered = sorted(events, key=lambda e: e["t_match_seconds"])
    for i, ev in enumerate(ordered):
        if ev["type"] != "shot":
            continue
        for prev in reversed(ordered[:i]):
            if ev["t_match_seconds"] - prev["t_match_seconds"] > KEY_PASS_WINDOW_SECONDS:
                break
            if prev["team"] != ev["team"] and prev["type"] in {"tackle", "interception", "pass", "gk_pass"}:
                break  # opponent touched the ball: no assist chain
            if prev["type"] == "pass" and prev["team"] == ev["team"]:
                if prev["attributes"].get("completed") is not False and "key_pass" not in prev["attributes"]:
                    prev["attributes"]["key_pass"] = True
                    prev.setdefault("derived", []).append("key_pass")
                break


def route_for_review(events: list[dict[str, Any]], threshold: float | None = None) -> list[dict[str, Any]]:
    """Set review_status: ``pending`` (queue) below threshold or with issues, else ``auto``."""

    thr = review_threshold() if threshold is None else threshold
    for ev in events:
        low = ev["confidence"] < thr
        ev["review_status"] = "pending" if (low or ev.get("issues")) else "auto"
        ev["review_reason"] = (["low confidence"] if low else []) + list(ev.get("issues") or [])
    return events


def build_timeline(
    clip_results: list[tuple[Clip, list[dict[str, Any]]]], *, threshold: float | None = None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for clip, raw in clip_results:
        events.extend(clip_events_to_match(clip, raw))
    events = dedupe_events(events)
    derive_key_passes(events)
    return route_for_review(events, threshold)
