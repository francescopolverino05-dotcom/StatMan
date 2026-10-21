"""Human review: accept / edit / delete events, logged as corrections."""

from __future__ import annotations

from typing import Any

from statman.autotag.repo import EDITABLE, EventRepo, get_repo
from statman.autotag.taxonomy import normalize_event

ACTIONS = ("accept", "edit", "delete")


def review_queue(match_id: str, repo: EventRepo | None = None) -> list[dict[str, Any]]:
    repo = repo or get_repo()
    rows = [e for e in repo.list_events(match_id) if e["review_status"] == "pending"]
    return sorted(rows, key=lambda e: (e["confidence"] if e["confidence"] is not None else -1, e["t_match_seconds"]))


def _snapshot(ev: dict[str, Any], keys: list[str] | tuple[str, ...]) -> dict[str, Any]:
    return {k: ev.get(k) for k in keys}


def apply_review(
    match_id: str,
    event_id: int,
    action: str,
    *,
    changes: dict[str, Any] | None = None,
    reviewer: str | None = None,
    note: str | None = None,
    repo: EventRepo | None = None,
) -> dict[str, Any]:
    """Apply one review decision. Returns {event, correction}."""

    repo = repo or get_repo()
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    ev = repo.get_event(match_id, event_id)
    if ev is None:
        raise KeyError(f"event {event_id} not found")

    if action == "accept":
        fields = {"review_status": "confirmed"}
        before = _snapshot(ev, ["review_status"])
    elif action == "delete":
        fields = {"review_status": "rejected"}
        before = _snapshot(ev, ["review_status"])
    else:
        changes = {k: v for k, v in (changes or {}).items() if k in EDITABLE}
        if not changes:
            raise ValueError(f"edit needs at least one of {EDITABLE}")
        merged = {**ev, **changes, "confidence": 1.0}
        if "attributes" in changes:
            merged["attributes"] = dict(changes["attributes"] or {})
        normalized, issues = normalize_event(merged)
        if normalized is None:
            raise ValueError("; ".join(issues))
        hard = [i for i in issues if i.startswith(("invalid", "dropped", "team"))]
        if hard:
            raise ValueError("; ".join(hard))
        fields = {k: normalized[k] for k in EDITABLE}
        fields.update({"review_status": "corrected", "review_reason": [], "issues": []})
        before = _snapshot(ev, [k for k in EDITABLE if ev.get(k) != fields[k]] + ["review_status"])

    after = {k: fields[k] for k in before}
    updated = repo.update_event(match_id, event_id, fields)
    correction = repo.add_correction(match_id, {
        "event_id": event_id, "action": action, "reviewer": reviewer, "note": note,
        "before": before, "after": after,
    })
    return {"event": updated, "correction": correction}


def add_human_event(match_id: str, raw: dict[str, Any], *, reviewer: str | None = None,
                    repo: EventRepo | None = None) -> dict[str, Any]:
    """Reviewer adds an event the tagger missed."""

    repo = repo or get_repo()
    normalized, issues = normalize_event({**raw, "confidence": 1.0})
    if normalized is None:
        raise ValueError("; ".join(issues))
    normalized.update({
        "video_ts_seconds": raw.get("video_ts_seconds"), "review_status": "confirmed",
        "source": "human", "issues": [], "review_reason": [], "clip_ids": [],
    })
    ev = repo.add_event(match_id, normalized)
    correction = repo.add_correction(match_id, {
        "event_id": ev["id"], "action": "add", "reviewer": reviewer, "note": None,
        "before": {}, "after": {k: ev.get(k) for k in ("type", "team", "shirt", "t_match_seconds", "attributes")},
    })
    return {"event": ev, "correction": correction}
