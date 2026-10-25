"""Per-clip quality checks for auto-tag output, plus the corrective re-tag prompt.

Replicates the checks done by hand on model output: condensed answers (too few
passes), only completed passes, missing end points, clocks outside the clip,
impossible coordinates, duplicates, silent stretches without a GAP marker,
keeper catches logged as SAVE, a team missing entirely, invented cards/corners.

``check_clip`` returns ``{"score", "passed", "hard", "soft", "stats"}``. Hard
issues fail the clip (-> automatic re-tag, then review flagging); soft issues
are only reported. Thresholds come from env (see ``thresholds``).
"""

from __future__ import annotations

import os
from typing import Any

DEFAULTS: dict[str, float] = {
    "STATMAN_QA_MIN_PASSES": 12,          # passes per 60 s of open play
    "STATMAN_QA_MIN_FAIL_RATE": 0.05,     # failed-pass share must reach this ...
    "STATMAN_QA_FAIL_RATE_MIN_PASSES": 15,  # ... once a clip has at least this many passes
    "STATMAN_QA_MAX_MISSING_END": 0.10,   # share of passes without x2,y2
    "STATMAN_QA_MAX_MISSING_START": 0.10,  # share of non-GAP events without x1,y1
    "STATMAN_QA_MAX_SILENCE": 20,         # seconds without any event and no GAP
    "STATMAN_QA_GAP_SHARE": 0.5,          # clip counts as "mostly GAP" above this share
    "STATMAN_QA_TEAM_MIN_EVENTS": 15,     # one team absent with >= this many events = hard
    "STATMAN_QA_SAVE_WINDOW": 6,          # SAVE must follow an on-target SHOT within N s
    "STATMAN_QA_MAX_CORNERS": 2,          # soft flag above this per clip
    "STATMAN_QA_DUP_WINDOW": 0.6,         # identical events within N s = duplicate
    # Napoli-Spezia hand tags peak at 38 events / 60 s (0.63/s) with 54-64 % of gaps on the modal
    # whole second (mm:ss clocks); the fabricated AI run had ~1.0/s and 88 % of gaps exactly 1 s.
    "STATMAN_QA_MAX_RATE": 0.75,          # events per second of open play above this = fabricated cadence
    "STATMAN_QA_EVEN_GAP_SHARE": 0.75,    # share of inter-event gaps with the same length (0.1 s) above this ...
    "STATMAN_QA_EVEN_MIN_EVENTS": 12,     # ... once a clip has at least this many timed events ...
    "STATMAN_QA_EVEN_MIN_RATE": 0.4,      # ... and at least this many events per second
    "STATMAN_QA_SHIRT_MIN_EVENTS": 10,    # with a lineup given, zero shirt numbers in >= this many events = hard
}
RETAG_MAX_DEFAULT = 2
JOB_MAX_COST_DEFAULT = 4.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else float(default)
    except ValueError:
        return float(default)


def thresholds() -> dict[str, float]:
    return {k: _env_float(k, v) for k, v in DEFAULTS.items()}


def enabled() -> bool:
    return os.environ.get("STATMAN_QUALITY", "on").strip().lower() not in {"off", "0", "false", "no"}


def retag_max() -> int:
    return max(0, int(_env_float("STATMAN_RETAG_MAX", RETAG_MAX_DEFAULT)))


def job_max_cost() -> float:
    return _env_float("STATMAN_JOB_MAX_COST", JOB_MAX_COST_DEFAULT)


def _num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _code(e: dict[str, Any]) -> str:
    return str(e.get("code") or e.get("type") or "").strip().upper()


def _is_gap(e: dict[str, Any]) -> bool:
    return _code(e) == "GAP" or str(e.get("type") or "").lower() == "gap"


def _is_pass(e: dict[str, Any]) -> bool:
    return str(e.get("type") or "").lower() == "pass" or _code(e) in {"PASS", "CROSS"}


def _pass_failed(e: dict[str, Any]) -> bool:
    if str(e.get("outcome") or "").lower() == "fail":
        return True
    return (e.get("attributes") or {}).get("completed") is False


def _t(e: dict[str, Any]) -> float | None:
    return _num(e.get("t_clip_seconds"))


def _issue(code: str, message: str, hint: str) -> dict[str, str]:
    return {"code": code, "message": message, "hint": hint}


def cadence_stats(events: list[dict[str, Any]], open_secs: float) -> dict[str, Any]:
    """Events per open-play second and the share of inter-event gaps that have the modal length (0.1 s bins)."""

    ts = sorted(t for t in (_t(e) for e in events if not _is_gap(e)) if t is not None)
    gaps = [round(b - a, 1) for a, b in zip(ts, ts[1:])]
    rate = len(ts) / open_secs if open_secs > 0 else 0.0
    if not gaps:
        return {"rate": round(rate, 3), "modal_gap": None, "modal_gap_share": 0.0}
    counts: dict[float, int] = {}
    for g in gaps:
        counts[g] = counts.get(g, 0) + 1
    modal, n = max(counts.items(), key=lambda kv: kv[1])
    return {"rate": round(rate, 3), "modal_gap": modal, "modal_gap_share": round(n / len(gaps), 3)}


def check_clip(events: list[dict[str, Any]] | None, duration: float, *, error: str | None = None,
               th: dict[str, float] | None = None, lineup_given: bool = False) -> dict[str, Any]:
    th = th or thresholds()
    hard: list[dict[str, str]] = []
    soft: list[dict[str, str]] = []
    duration = float(duration or 60.0)
    if error is not None or events is None:
        hard.append(_issue("parse_failure", f"no valid JSON event list ({error or 'no output'})",
                           'answer with valid JSON only: {"events": [...]} following the schema exactly'))
        return {"score": 0.0, "passed": False, "hard": hard, "soft": soft, "stats": {"events": 0}}

    timed = sorted((e for e in events if _t(e) is not None), key=lambda e: _t(e))
    gaps = [e for e in events if _is_gap(e)]
    play = [e for e in events if not _is_gap(e)]
    passes = [e for e in play if _is_pass(e)]
    failed = [e for e in passes if _pass_failed(e)]

    # Seconds covered by GAP markers: from each GAP to the next non-GAP event (or clip end).
    gap_secs = 0.0
    for i, e in enumerate(timed):
        if _is_gap(e):
            nxt = next((_t(x) for x in timed[i + 1:] if not _is_gap(x)), duration)
            gap_secs += max(0.0, min(nxt, duration) - _t(e))
    gap_share = gap_secs / duration if duration else 0.0
    open_secs = max(0.0, duration - gap_secs)
    stats = {"events": len(events), "passes": len(passes), "failed_passes": len(failed),
             "gaps": len(gaps), "gap_share": round(gap_share, 2)}

    zone_mode = any("coord_confidence" in (e.get("attributes") or {}) or "t_video_raw" in e for e in events)
    cad = cadence_stats(events, open_secs)
    stats.update(rate=cad["rate"], modal_gap=cad["modal_gap"], modal_gap_share=cad["modal_gap_share"])
    if cad["rate"] > th["STATMAN_QA_MAX_RATE"]:
        hard.append(_issue(
            "fixed_cadence", f"{cad['rate']:.2f} events/s of open play (max {th['STATMAN_QA_MAX_RATE']:.2f})",
            f"your previous answer had {len(play)} events in {open_secs:.0f} s, about one per "
            f"{1 / max(cad['rate'], 1e-6):.1f} s: that is a fixed cadence, not real play. Log only the events you "
            "actually see, at their real time"))
    n_timed = len([e for e in timed if not _is_gap(e)])
    if n_timed >= th["STATMAN_QA_EVEN_MIN_EVENTS"] and cad["modal_gap_share"] > th["STATMAN_QA_EVEN_GAP_SHARE"] \
            and cad["rate"] >= th["STATMAN_QA_EVEN_MIN_RATE"]:
        hard.append(_issue(
            "even_spacing", f"{cad['modal_gap_share']:.0%} of gaps between events are exactly {cad['modal_gap']} s",
            f"{cad['modal_gap_share']:.0%} of your events were exactly {cad['modal_gap']} s apart: real events are "
            "not evenly spaced. Use the real timestamp of each event and leave out events you did not see"))
    shirts = sum(1 for e in play if e.get("shirt") not in (None, ""))
    stats["shirts"] = shirts
    if lineup_given and len(play) >= th["STATMAN_QA_SHIRT_MIN_EVENTS"] and shirts == 0:
        hard.append(_issue(
            "no_shirt_numbers", f"0 shirt numbers in {len(play)} events although the lineup was given",
            "you gave no shirt number at all although the lineup is provided: read the numbers on the shirts (and in "
            "close-ups/replays) and set shirt for every event where it is readable; null only when it is not"))
    if gap_share < th["STATMAN_QA_GAP_SHARE"]:
        need = int(round(th["STATMAN_QA_MIN_PASSES"] * open_secs / 60.0))
        if len(passes) < need:
            hard.append(_issue(
                "too_few_passes", f"only {len(passes)} passes for {open_secs:.0f} s of open play (min {need})",
                f"your previous answer had only {len(passes)} passes and {len(failed)} failed passes; you condensed "
                "the play. Log EVERY pass individually, one event per touch-to-touch pass, including misplaced ones"))
    if len(passes) >= th["STATMAN_QA_FAIL_RATE_MIN_PASSES"]:
        rate = len(failed) / len(passes)
        stats["fail_rate"] = round(rate, 3)
        if rate < th["STATMAN_QA_MIN_FAIL_RATE"]:
            hard.append(_issue(
                "no_failed_passes", f"pass fail rate {rate:.0%} ({len(failed)}/{len(passes)})",
                f"you marked {len(passes) - len(failed)} of {len(passes)} passes as success; real play has misplaced, "
                "intercepted and out-of-play passes - log them with outcome fail"))
    if passes:
        miss = [e for e in passes if _num(e.get("x2")) is None or _num(e.get("y2")) is None]
        if len(miss) / len(passes) > th["STATMAN_QA_MAX_MISSING_END"]:
            (soft if zone_mode else hard).append(_issue("missing_end_points", f"{len(miss)}/{len(passes)} passes without x2,y2",
                               f"{len(miss)} passes had no end point: give x2,y2 (where the pass ended) for every pass"))
    if play:
        miss = [e for e in play if _num(e.get("x")) is None or _num(e.get("y")) is None]
        if len(miss) / len(play) > th["STATMAN_QA_MAX_MISSING_START"]:
            (soft if zone_mode else hard).append(_issue("missing_coordinates", f"{len(miss)}/{len(play)} events without x1,y1",
                               f"{len(miss)} events had no coordinates: give x1,y1 for every on-ball event"))
    outside = [e for e in events if e.get("clock_outside")]
    if outside:
        hard.append(_issue("clock_outside_clip", f"{len(outside)} events with a clock outside the clip window",
                           f"{len(outside)} events had a clock outside this clip: use clip start clock + seconds "
                           "into the clip, within the start/end clocks given"))
    bad = [e for e in events for k in ("x", "y", "x2", "y2")
           if _num(e.get(k)) is not None and not 0.0 <= _num(e.get(k)) <= 100.0]
    if bad:
        hard.append(_issue("coords_out_of_range", f"{len(bad)} coordinates outside 0-100",
                           "some coordinates were outside 0-100: every x/y must be between 0 and 100"))
    dups = 0
    win = th["STATMAN_QA_DUP_WINDOW"]
    for i, a in enumerate(timed):
        for b in timed[i + 1:]:
            if _t(b) - _t(a) > win:
                break
            if all(a.get(k) == b.get(k) for k in ("code", "type", "team", "shirt", "x", "y", "x2", "y2", "outcome")):
                dups += 1
    if dups:
        hard.append(_issue("duplicates", f"{dups} duplicate events",
                           f"{dups} events were repeated: log each action exactly once"))
    silence = th["STATMAN_QA_MAX_SILENCE"]
    prev_t, prev_gap, silent = 0.0, False, []
    for e in timed + [{"t_clip_seconds": duration, "_end": True}]:
        t = _t(e)
        if t - prev_t > silence and not prev_gap:
            silent.append((prev_t, t))
        prev_t, prev_gap = t, _is_gap(e)
    if silent:
        spans = ", ".join(f"{a:.0f}-{b:.0f}s" for a, b in silent)
        hard.append(_issue("silent_stretch", f"no events and no GAP for >{silence:.0f} s ({spans})",
                           f"nothing was logged between {spans} of the clip: log the play there, or one GAP event if "
                           "the camera was off the ball"))
    win = th["STATMAN_QA_SAVE_WINDOW"]
    orphan = 0
    for e in timed:
        if _code(e) == "SAVE" or str(e.get("type") or "").lower() == "save":
            t = _t(e)
            shot = any((_code(s) == "SHOT" or str(s.get("type") or "") == "shot") and s.get("team") != e.get("team")
                       and str(s.get("outcome") or (s.get("attributes") or {}).get("outcome") or "").lower()
                       in {"on", "saved"} and 0 <= t - _t(s) <= win for s in timed)
            orphan += not shot
    if orphan:
        hard.append(_issue("save_without_shot", f"{orphan} SAVE without a preceding on-target SHOT",
                           f"{orphan} SAVE events had no on-target SHOT before them: a keeper catching or claiming a "
                           "cross is RECOVERY, SAVE only after a SHOT with outcome on"))
    teams = {e.get("team") for e in play}
    if len(play) >= th["STATMAN_QA_TEAM_MIN_EVENTS"]:
        for side in ("home", "away"):
            if side not in teams:
                hard.append(_issue("team_missing", f"no events for {side} in {len(play)} events",
                                   f"your answer had no events for the {side} team: log both teams' actions"))
    cards = [e for e in play if _code(e) == "CARD"]
    if cards:
        soft.append(_issue("cards", f"{len(cards)} cards in one clip", "only log a CARD when the referee shows it"))
    corners = [e for e in play if _code(e) == "CORNER"]
    if len(corners) > th["STATMAN_QA_MAX_CORNERS"]:
        soft.append(_issue("corners", f"{len(corners)} corners in one clip", "only log a CORNER taken from the arc"))

    score = max(0.0, 100.0 - 25.0 * len(hard) - 5.0 * len(soft))
    return {"score": score, "passed": not hard, "hard": hard, "soft": soft, "stats": stats}


def rank(q: dict[str, Any]) -> tuple:
    """Sort key for picking the best attempt: score, then fewer hard issues, then more events."""
    return (q["score"], -len(q["hard"]), q["stats"].get("events", 0))


def corrective_text(q: dict[str, Any], attempt: int) -> str:
    lines = [f"CORRECTION (re-tag attempt {attempt}): your previous answer for this clip failed quality checks."]
    lines += [f"- {i['hint']}." for i in q["hard"] + q["soft"]]
    lines.append("Watch the whole clip again and return the complete event list, not a summary.")
    return "\n".join(lines)


def issue_summary(q: dict[str, Any]) -> str:
    return "; ".join(i["message"] for i in q["hard"])
