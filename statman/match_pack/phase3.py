"""Phase 3 orchestration: team tracking → merge possession + split film counts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from statman.match_pack import store
from statman.match_pack.film_merge import merge_film_into_sheet
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.match_pack.tracking import (
    TrackingConfig,
    assign_events_to_teams,
    run_team_tracking,
)

_LOCK = threading.Lock()
_ACTIVE_PACK: str | None = None

PHASE = "match-pack-phase3"


def _tracking_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "tracking.json"


def _film_events_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_events.json"


def _film_stats_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_stats.json"


def _corrected_path(pack_id: str) -> Path:
    return store.pack_dir(pack_id) / "film_corrected.json"


def merge_tracking_into_sheet(
    sheet: dict[str, Any],
    tracking: dict[str, Any],
    team_splits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fill possession + approximate team-split shots/passes from Phase 3."""
    out = dict(sheet)
    poss = (tracking or {}).get("possession") or {}
    splits = team_splits or {}
    home_split = splits.get("home") or {}
    away_split = splits.get("away") or {}

    teams = []
    for idx, team in enumerate(out.get("teams") or []):
        t = dict(team)
        side = "home" if idx == 0 else "away"
        split = home_split if side == "home" else away_split
        prov = dict(t.get("provenance") or {})
        sections = dict(t.get("sections") or {})
        match_sec = dict(sections.get("match") or {})
        attack = dict(sections.get("attack") or {})
        passes = dict(sections.get("passes") or {})

        pct = poss.get("home_pct") if side == "home" else poss.get("away_pct")
        if pct is not None:
            t["possession_pct"] = pct
            match_sec["possession_pct"] = pct
            prov["possession_pct"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "kit-cluster ball-handler possession (unknown frames ignored)",
            }

        if split.get("shots") is not None:
            t["shots"] = int(split["shots"])
            attack["shots"] = int(split["shots"])
            prov["shots"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "film Shot+Goal tags assigned via possession timeline",
            }
        if split.get("passes") is not None:
            t["passes_attempted"] = int(split["passes"])
            passes["passes_attempted"] = int(split["passes"])
            # Still no completions.
            prov["pass_accuracy"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": f"passes attempted≈{split['passes']} from film tags; completion unknown",
            }
        if split.get("tackles") is not None:
            t["tackles"] = int(split["tackles"])
            defence = dict(sections.get("defence") or {})
            defence["tackles"] = int(split["tackles"])
            sections["defence"] = defence
            prov["tackles"] = {
                "status": "approximate_video",
                "phase": PHASE,
                "detail": "film tackle tags assigned via possession timeline",
            }

        sections["match"] = match_sec
        sections["attack"] = attack
        sections["passes"] = passes
        t["sections"] = sections
        t["provenance"] = prov
        teams.append(t)
    out["teams"] = teams

    out["tracking"] = {
        "phase": PHASE,
        "method": tracking.get("method"),
        "possession": poss,
        "cluster_to_side": tracking.get("cluster_to_side"),
        "mapping_source": tracking.get("mapping_source"),
        "samples": tracking.get("samples"),
        "team_splits": {
            "home": {k: v for k, v in home_split.items() if k != "labels"},
            "away": {k: v for k, v in away_split.items() if k != "labels"},
            "events_tagged": splits.get("events_tagged"),
            "events_total": splits.get("events_total"),
        },
        "warning": tracking.get("warning"),
    }

    src = dict(out.get("source") or {})
    cov = dict(src.get("coverage") or {})
    pending = [
        f
        for f in (cov.get("pending_later_phases") or [])
        if f not in {"possession_pct", "shots", "tackles"}
    ]
    approx = sorted(
        set(cov.get("approximate_video") or [])
        | {"possession_pct", "shots", "passes_attempted", "tackles"}
    )
    cov["pending_later_phases"] = pending
    cov["approximate_video"] = approx
    cov["phase3"] = {
        "possession_home_pct": poss.get("home_pct"),
        "possession_away_pct": poss.get("away_pct"),
        "shots_home": home_split.get("shots"),
        "shots_away": away_split.get("shots"),
        "passes_home": home_split.get("passes"),
        "passes_away": away_split.get("passes"),
    }
    src["coverage"] = cov
    src["phase"] = PHASE
    src["quality"] = "fact_plus_film_plus_tracking"
    note = (src.get("note") or "").rstrip()
    src["note"] = (
        f"{note} Phase 3: kit-cluster tracking filled possession and "
        "home/away film-tag splits (approximate)."
    ).strip()
    out["source"] = src
    return out


def apply_phase3_to_sheet(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    facts = meta.get("facts")
    if not facts:
        raise ValueError("Facts required before Phase 3 merge")
    tpath = _tracking_path(pack_id)
    if not tpath.exists():
        raise ValueError("No tracking.json — run Phase 3 first")
    tracking = json.loads(tpath.read_text(encoding="utf-8"))
    # Drop bulky timeline from sheet payload; keep on disk.
    tracking_light = {k: v for k, v in tracking.items() if k != "timeline"}
    splits = tracking.get("team_splits") or {}

    sheet = sheet_from_facts(facts, pack_id=pack_id)
    if _film_stats_path(pack_id).exists():
        film_stats = json.loads(_film_stats_path(pack_id).read_text(encoding="utf-8"))
        sheet = merge_film_into_sheet(sheet, film_stats, pack_id=pack_id)
        # Keep reconcile overlay if present.
        if _corrected_path(pack_id).exists():
            corrected = json.loads(_corrected_path(pack_id).read_text(encoding="utf-8"))
            film = dict(sheet.get("film") or {})
            film["corrected"] = {
                "goals": corrected.get("corrected_totals", {}).get("goals"),
                "goal_tags_raw": corrected.get("corrected_totals", {}).get("goal_tags_raw"),
                "goal_tags_matched": corrected.get("corrected_totals", {}).get(
                    "goal_tags_matched"
                ),
                "anchored_goals": corrected.get("anchored_goals"),
            }
            sheet["film"] = film

    sheet = merge_tracking_into_sheet(sheet, tracking_light, splits)
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["tracking_path"] = str(tpath)
    meta["status"] = "phase3_ready"
    meta["phase"] = PHASE
    meta["coverage"] = sheet["source"]["coverage"]
    store.write_meta(pack_id, meta)
    return meta


def start_phase3(
    pack_id: str,
    *,
    sample_fps: float = 0.25,
    max_duration_sec: float | None = None,
    start_sec: float = 0.0,
) -> dict[str, Any]:
    """Start Phase-3 tracking on the pack video (background thread)."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    path = Path(video.get("path") or "")
    if not path.exists():
        raise ValueError("Pack video missing — upload video first")

    phase3 = meta.get("phase3") or {}
    if phase3.get("status") in {"queued", "running"}:
        return meta

    cfg = TrackingConfig(sample_fps=sample_fps, start_sec=float(start_sec or 0.0))
    if max_duration_sec is not None:
        cfg.max_duration_sec = float(max_duration_sec)

    meta["phase3"] = {
        "status": "queued",
        "progress": {"stage": "queued", "pct": 0},
        "config": {
            "sample_fps": cfg.sample_fps,
            "max_duration_sec": cfg.max_duration_sec,
            "start_sec": cfg.start_sec,
        },
        "error": None,
        "cancel_requested": False,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)

    def _run() -> None:
        global _ACTIVE_PACK
        with _LOCK:
            while _ACTIVE_PACK is not None:
                time.sleep(1.0)
                cur = store.read_meta(pack_id) or {}
                if (cur.get("phase3") or {}).get("cancel_requested"):
                    p = cur.get("phase3") or {}
                    p["status"] = "cancelled"
                    cur["phase3"] = p
                    store.write_meta(pack_id, cur)
                    return
            _ACTIVE_PACK = pack_id
        try:
            _process(pack_id, cfg)
        finally:
            with _LOCK:
                if _ACTIVE_PACK == pack_id:
                    _ACTIVE_PACK = None

    threading.Thread(target=_run, name=f"statman-phase3-{pack_id}", daemon=True).start()
    return store.read_meta(pack_id) or meta


def cancel_phase3(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    p = dict(meta.get("phase3") or {})
    if p.get("status") in {"done", "error", "cancelled", None}:
        return meta
    p["cancel_requested"] = True
    if p.get("status") == "queued":
        p["status"] = "cancelled"
        p["error"] = "Cancelled before tracking started"
    else:
        p["status"] = "cancelling"
    meta["phase3"] = p
    store.write_meta(pack_id, meta)
    return meta


def _process(pack_id: str, cfg: TrackingConfig) -> None:
    meta = store.read_meta(pack_id)
    if meta is None:
        return
    p = dict(meta.get("phase3") or {})
    p.update({"status": "running", "progress": {"stage": "starting", "pct": 1}, "error": None})
    meta["phase3"] = p
    store.write_meta(pack_id, meta)

    def on_progress(payload: dict[str, Any]) -> None:
        cur = store.read_meta(pack_id)
        if cur is None:
            return
        phase = dict(cur.get("phase3") or {})
        if phase.get("cancel_requested"):
            return
        phase["status"] = "running"
        phase["progress"] = payload
        phase["updated_at"] = time.time()
        cur["phase3"] = phase
        store.write_meta(pack_id, cur)

    def should_cancel() -> bool:
        cur = store.read_meta(pack_id) or {}
        return bool((cur.get("phase3") or {}).get("cancel_requested"))

    try:
        anchored = []
        facts = meta.get("facts") or {}
        if isinstance(facts.get("film_corrected"), dict):
            anchored = list(facts["film_corrected"].get("anchored_goals") or [])
        elif _corrected_path(pack_id).exists():
            corrected = json.loads(_corrected_path(pack_id).read_text(encoding="utf-8"))
            anchored = list(corrected.get("anchored_goals") or [])

        video_path = Path((meta.get("video") or {})["path"])
        tracking = run_team_tracking(
            video_path,
            config=cfg,
            anchored_goals=anchored,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        if should_cancel():
            raise InterruptedError("cancelled")

        team_splits: dict[str, Any] = {}
        if _film_events_path(pack_id).exists():
            events = json.loads(_film_events_path(pack_id).read_text(encoding="utf-8"))
            team_splits = assign_events_to_teams(events, tracking.get("timeline") or [])
            tracking["team_splits"] = team_splits

        _tracking_path(pack_id).write_text(
            json.dumps(tracking, indent=2, default=str), encoding="utf-8"
        )

        meta = apply_phase3_to_sheet(pack_id)
        p = dict(meta.get("phase3") or {})
        p.update(
            {
                "status": "done",
                "progress": {"stage": "done", "pct": 100},
                "possession": tracking.get("possession"),
                "team_splits": {
                    k: tracking.get("team_splits", {}).get(k)
                    for k in ("home", "away", "events_tagged", "events_total")
                },
                "error": None,
                "updated_at": time.time(),
            }
        )
        meta["phase3"] = p
        store.write_meta(pack_id, meta)
    except InterruptedError:
        meta = store.read_meta(pack_id) or meta
        p = dict(meta.get("phase3") or {})
        p["status"] = "cancelled"
        p["error"] = "Cancelled during tracking"
        p["progress"] = {**(p.get("progress") or {}), "stage": "cancelled"}
        meta["phase3"] = p
        store.write_meta(pack_id, meta)
    except Exception as exc:  # noqa: BLE001
        meta = store.read_meta(pack_id) or meta
        p = dict(meta.get("phase3") or {})
        p["status"] = "error"
        p["error"] = str(exc)
        p["progress"] = {**(p.get("progress") or {}), "stage": "error"}
        meta["phase3"] = p
        store.write_meta(pack_id, meta)
