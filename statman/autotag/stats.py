"""Team and player stats from tagged events (match totals, no half split).

These definitions port the hand pipeline (``napoli-spezia/build3.py``, used for
the published Napoli-Spezia page) so the app and the hand numbers agree when
fed the same tags. Every team total is a direct count of logged events over
the whole match: nothing is scaled, sampled or extrapolated. Anything that is
not a full direct count is listed in ``stat_flags`` (status ``estimated`` or
``partial`` plus reasons) and shown as such in the UI and CSV.

Coordinates: x/y 0..100 from the acting team's view, x=100 = the goal it
attacks (105 x 68 m pitch for distances).

* Event codes: analyst codes (PASS, CROSS, FK, ...) when present, else derived
  from the type (``event_code``). As in build3.py an INTERCEPT whose detail
  says "tackle" is a TACKLE, and one saying claim / blocks cross / concedes
  corner / out for throw is not an interception (claim, block, clearance).
* Completed: ``completed``/``won`` attribute, else outcome success/goal.
* passes: PASS + GK_PASS + FK + GOALKICK + THROW (crosses and corners are
  separate). FKs tagged as a direct shot are not passes.
* possession_pct: team share of all passes attempted (as above).
* Progressive Passes (line-breaking, build3.py geometric rule): passes and
  crosses with start and end whose distance to the target goal centre
  shrinks by >= 30 m inside the own half, >= 15 m when crossing halfway,
  >= 10 m from the opponent half. Attempted (any outcome), completed, %.
* PPDA (Bodo method, exactly build3.py): opponent PASS + CROSS events
  starting at x <= 60 / our interceptions + tackles + fouls + won duels at
  x >= 40. Events without x are left out (``ppda_events_without_x``).
* xg: sum of the tagger's per-shot values (estimate; missing values add 0).
* gk_saves: SAVE events that are not keeper claims/catches and follow an
  opponent saved shot within 0-3 s (build3.py rule).
* Rejected events are excluded. Pending events are included unless
  ``confirmed_only`` is set; ``pending_review`` says how many there are.
"""

from __future__ import annotations

import csv
import io
import math
from collections import Counter, defaultdict
from typing import Any

TEAMS = ("home", "away")
COUNTED = {"auto", "confirmed", "corrected", "pending"}
REVIEWED = {"auto", "confirmed", "corrected"}


def _pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 1) if den else None


def _other(team: str) -> str:
    return "away" if team == "home" else "home"


def usable_events(events: list[dict[str, Any]], *, confirmed_only: bool = False) -> list[dict[str, Any]]:
    allowed = REVIEWED if confirmed_only else COUNTED
    return [e for e in events if e.get("review_status") in allowed and e.get("team") in TEAMS]


def _a(ev: dict[str, Any], key: str) -> Any:
    return (ev.get("attributes") or {}).get(key)


# --- build3.py-compatible event helpers ------------------------------------

PASS_CODES = ("PASS", "GK_PASS", "FK", "GOALKICK", "THROW")
PPDA_PASS_CODES = ("PASS", "CROSS")
PPDA_DEF_CODES = ("INTERCEPT", "TACKLE", "FOUL")
PPDA_OPP_PASS_MAX_X = 60.0   # opponent passes starting in their first 60 % of the pitch
PPDA_DEF_MIN_X = 40.0        # our defensive actions outside our own defensive 40 %
PPDA_DEFINITION = (
    "PPDA (Bodø method, as the hand pipeline): opponent passes and crosses starting at x ≤ 60 "
    "(their first 60% of the pitch) ÷ our interceptions, tackles, fouls and won duels at x ≥ 40. "
    "x = 0..100 from the acting team's view (100 = goal it attacks). Lower = more intense pressing."
)
PROGRESSIVE_DEFINITION = (
    "Progressive Passes (line-breaking, hand-pipeline rule): passes and crosses that move the ball at least "
    "30 m closer to the target goal within the own half, 15 m when crossing halfway, or 10 m in the opponent "
    "half (105×68 m pitch). Attempted / completed / success %."
)
_TYPE_CODE = {"pass": "PASS", "gk_pass": "GK_PASS", "free_kick": "FK", "throw_in": "THROW", "goal_kick": "GOALKICK",
              "interception": "INTERCEPT", "tackle": "TACKLE", "foul": "FOUL", "duel": "DUEL", "shot": "SHOT",
              "save": "SAVE", "corner": "CORNER", "clearance": "CLEAR", "recovery": "RECOVERY",
              "aerial_duel": "AERIAL", "ball_lost": "LOST", "card": "CARD", "gap": "GAP"}
_NOT_INTERCEPT = ("claim", "blocks cross", "concedes corner", "out for throw")


def _detail(e: dict[str, Any]) -> str:
    return str(e.get("detail") or "").lower()


def event_code(e: dict[str, Any]) -> str:
    """Analyst code with build3.py's authoritative reclassifications applied."""

    code = str(e.get("code") or "").upper() or _TYPE_CODE.get(e.get("type"), str(e.get("type") or "").upper())
    if e.get("type") == "pass" and code == "PASS" and _a(e, "cross") is True:
        code = "CROSS"
    if code == "INTERCEPT":
        d = _detail(e)
        if "tackle" in d:
            return "TACKLE"
        if any(k in d for k in _NOT_INTERCEPT):
            return "BLOCK" if "block" in d else ("GKCLAIM" if "claim" in d else "CLEAR")
    return code


def is_ok(e: dict[str, Any]) -> bool:
    for k in ("completed", "won"):
        v = _a(e, k)
        if v is not None:
            return v is True
    return str(e.get("outcome") or "").lower() in {"success", "goal"}


def is_pass(e: dict[str, Any]) -> bool:
    c = event_code(e)
    if c == "FK" and _a(e, "outcome") == "direct_shot":
        return False
    return c in PASS_CODES


def _has_line(e: dict[str, Any]) -> bool:
    return all(e.get(k) is not None for k in ("x", "y", "x2", "y2"))


def _dgoal(x: float, y: float) -> float:
    return math.hypot(105 - x * 1.05, 34 - y * 0.68)


def is_progressive(e: dict[str, Any]) -> bool:
    """build3.py ``isprog``: geometric progressive (line-breaking) pass."""

    if not _has_line(e):
        return False
    gain = _dgoal(e["x"], e["y"]) - _dgoal(e["x2"], e["y2"])
    a, b = e["x"], e["x2"]
    if a < 50 and b < 50:
        return gain >= 30
    if a < 50 <= b:
        return gain >= 15
    return gain >= 10


def coords_estimated(e: dict[str, Any]) -> bool:
    """Zone-mode AI pass whose coordinate confidence was low: geometry is a guess, not a measurement."""
    return bool(_a(e, "coords_estimated"))


def _prog_candidate(e: dict[str, Any]) -> bool:
    return is_pass(e) or event_code(e) == "CROSS"


def _is_save(e: dict[str, Any], opp_shots: list[dict[str, Any]]) -> bool:
    if event_code(e) != "SAVE" or "claim" in _detail(e) or "catch" in _detail(e):
        return False
    t = e["t_match_seconds"]
    return any(_a(s, "outcome") == "saved" or (_a(s, "on_target") is True and _a(s, "outcome") != "goal")
               for s in opp_shots if 0 <= t - s["t_match_seconds"] <= 3)


def team_stats(events: list[dict[str, Any]], *, confirmed_only: bool = False) -> dict[str, Any]:
    evs = usable_events(events, confirmed_only=confirmed_only)
    by: dict[str, list[dict[str, Any]]] = {t: [e for e in evs if e["team"] == t] for t in TEAMS}
    all_passes = sum(1 for e in evs if is_pass(e))
    out: dict[str, Any] = {}
    for team in TEAMS:
        mine, opp = by[team], by[_other(team)]

        def n(etype: str, pred=lambda e: True, src=mine) -> int:
            return sum(1 for e in src if e["type"] == etype and pred(e))

        def nc(code: str, pred=lambda e: True, src=mine) -> int:
            return sum(1 for e in src if event_code(e) == code and pred(e))

        shots = [e for e in mine if e["type"] == "shot"]
        on_t = sum(1 for e in shots if _a(e, "on_target") is True)
        passes = [e for e in mine if is_pass(e)]
        completed = sum(1 for e in passes if is_ok(e))
        crosses = [e for e in mine if event_code(e) == "CROSS"]
        line_broken = Counter(_a(e, "line_broken") for e in mine if e["type"] == "pass" and _a(e, "line_broken"))

        cand = [e for e in mine if _prog_candidate(e)]
        prog_all = [e for e in cand if is_progressive(e)]
        prog = [e for e in prog_all if not coords_estimated(e)]
        prog_est = len(prog_all) - len(prog)
        prog_ok = sum(1 for e in prog if is_ok(e))

        opp_p = [e for e in opp if event_code(e) in PPDA_PASS_CODES]
        ppda_num = sum(1 for e in opp_p if e.get("x") is not None and e["x"] <= PPDA_OPP_PASS_MAX_X)
        def_actions = [e for e in mine if event_code(e) in PPDA_DEF_CODES or (event_code(e) == "DUEL" and is_ok(e))]
        ppda_den = sum(1 for e in def_actions if e.get("x") is not None and e["x"] >= PPDA_DEF_MIN_X)
        no_x = sum(1 for e in opp_p + def_actions if e.get("x") is None)

        opp_shots = [e for e in opp if e["type"] == "shot"]
        saves = sum(1 for e in mine if _is_save(e, opp_shots))
        conceded = n("goal", src=opp)
        gk_passes = [e for e in mine if e["type"] == "gk_pass"]
        gk_done = sum(1 for e in gk_passes if _a(e, "completed") is True)

        out[team] = {
            "goals": n("goal"),
            "possession_pct": _pct(len(passes), all_passes),
            "fouls": nc("FOUL"),
            "yellow_cards": n("card", lambda e: _a(e, "color") == "yellow"),
            "red_cards": n("card", lambda e: _a(e, "color") == "red"),
            "corners": n("corner"),
            "free_kicks_30m": n("free_kick"),
            "free_kicks_30m_direct_shot": n("free_kick", lambda e: _a(e, "outcome") == "direct_shot"),
            "free_kicks_30m_crossed_played": n("free_kick", lambda e: _a(e, "outcome") == "crossed_played"),
            "xg": round(sum(float(_a(e, "xg") or 0.0) for e in shots), 2),
            "xg_missing": sum(1 for e in shots if _a(e, "xg") is None),
            "shots": len(shots),
            "shots_on_target": on_t,
            "shots_off_target": sum(1 for e in shots if _a(e, "on_target") is False),
            "shot_accuracy_pct": _pct(on_t, len(shots)),
            "shots_inside_box": sum(1 for e in shots if _a(e, "inside_box") is True),
            "shots_outside_box": sum(1 for e in shots if _a(e, "inside_box") is False),
            "shots_headed": sum(1 for e in shots if _a(e, "headed") is True),
            "key_passes": n("pass", lambda e: _a(e, "key_pass") is True),
            "box_entries": n("pass", lambda e: _a(e, "box_entry") is True),
            "passes": len(passes),
            "passes_completed": completed,
            "pass_accuracy_pct": _pct(completed, len(passes)),
            "progressive_passes": len(prog),
            "progressive_passes_completed": prog_ok,
            "progressive_pass_pct": _pct(prog_ok, len(prog)),
            "progressive_candidates_without_coords": sum(1 for e in cand if not _has_line(e)),
            "progressive_passes_estimated": prog_est,
            "line_broken": dict(sorted(line_broken.items())),
            "crosses": len(crosses),
            "crosses_completed": sum(1 for e in crosses if is_ok(e)),
            "tackles": nc("TACKLE"),
            "interceptions": nc("INTERCEPT"),
            "ppda": round(ppda_num / ppda_den, 2) if ppda_den else None,
            "ppda_opponent_passes": ppda_num,
            "ppda_defensive_actions": ppda_den,
            "ppda_events_without_x": no_x,
            "balls_lost": n("ball_lost"),
            "balls_lost_miscontrol": n("ball_lost", lambda e: _a(e, "reason") == "miscontrol"),
            "balls_lost_dispossessed": n("ball_lost", lambda e: _a(e, "reason") == "dispossessed"),
            "aerials_won": n("aerial_duel", lambda e: _a(e, "won") is True),
            "aerials_lost": n("aerial_duel", lambda e: _a(e, "won") is False),
            "aerials_from_goal_kick": n("aerial_duel", lambda e: _a(e, "source") == "goal_kick"),
            "aerials_from_long_ball": n("aerial_duel", lambda e: _a(e, "source") == "long_ball"),
            "gk_saves": saves,
            "goals_conceded": conceded,
            "save_pct": _pct(saves, saves + conceded),
            "shots_faced": len(opp_shots),
            "on_target_faced": sum(1 for e in opp_shots if _a(e, "on_target") is True),
            "gk_passes": len(gk_passes),
            "gk_passes_completed": gk_done,
            "gk_pass_accuracy_pct": _pct(gk_done, len(gk_passes)),
            "gk_passes_short": sum(1 for e in gk_passes if _a(e, "length") == "short"),
            "gk_passes_long": sum(1 for e in gk_passes if _a(e, "length") == "long"),
            "gk_passes_middle": sum(1 for e in gk_passes if _a(e, "lane") == "middle"),
            "gk_passes_flank": sum(1 for e in gk_passes if _a(e, "lane") == "flank"),
        }
    return out


# Team metrics that are direct counts of logged events (affected by footage gaps / review state).
COUNTED_METRICS = (
    "passes", "passes_completed", "pass_accuracy_pct", "possession_pct", "progressive_passes",
    "progressive_passes_completed", "progressive_pass_pct", "ppda", "crosses", "crosses_completed", "tackles",
    "interceptions", "fouls", "shots", "shots_on_target", "balls_lost", "aerials_won", "aerials_lost",
    "key_passes", "gk_saves", "gk_passes", "corners",
)


def stat_flags(events: list[dict[str, Any]], teams: dict[str, Any], *, confirmed_only: bool = False) -> dict[str, Any]:
    """metric -> {status: 'estimated'|'partial', reasons: [...]} for anything that is not a full direct count."""

    live = [e for e in events if e.get("review_status") != "rejected"]
    evs = usable_events(events, confirmed_only=confirmed_only)
    flags: dict[str, dict[str, Any]] = {}

    def add(metric: str, status: str, reason: str) -> None:
        f = flags.setdefault(metric, {"status": status, "reasons": []})
        if status == "estimated":
            f["status"] = "estimated"
        if reason not in f["reasons"]:
            f["reasons"].append(reason)

    h, a = teams["home"], teams["away"]
    if h["shots"] or a["shots"]:
        miss = h["xg_missing"] + a["xg_missing"]
        add("xg", "estimated", "model value from the tagger, not a count"
            + (f"; {miss} shot(s) without a value add 0 (lower bound)" if miss else ""))
    gaps = [e for e in live if e.get("type") == "gap"]
    if gaps:
        for m in COUNTED_METRICS:
            add(m, "partial", f"{len(gaps)} footage gap(s) (camera off the ball / replay): play there is not tagged")
    flagged = sum(1 for e in live if e.get("review_status") == "pending"
                  and any("quality" in str(i) for i in (e.get("issues") or [])))
    pending = sum(1 for e in live if e.get("review_status") == "pending")
    if pending and not confirmed_only:
        why = f"{pending} event(s) still pending review"
        if flagged:
            why += f" ({flagged} from clips that failed quality checks)"
        for m in COUNTED_METRICS:
            add(m, "partial", why + "; counted as tagged")
    elif pending and confirmed_only:
        for m in COUNTED_METRICS:
            add(m, "partial", f"{pending} pending event(s) left out (confirmed only)")
    if h["ppda_events_without_x"] or a["ppda_events_without_x"]:
        add("ppda", "partial", f"{h['ppda_events_without_x'] + a['ppda_events_without_x']} PPDA event(s) without x left out")
    if h["progressive_candidates_without_coords"] or a["progressive_candidates_without_coords"]:
        k = h["progressive_candidates_without_coords"] + a["progressive_candidates_without_coords"]
        add("progressive_passes", "partial", f"{k} pass(es) without start+end coordinates cannot be tested")
    if h.get("progressive_passes_estimated") or a.get("progressive_passes_estimated"):
        k = h["progressive_passes_estimated"] + a["progressive_passes_estimated"]
        add("progressive_passes", "estimated",
            f"{k} more pass(es) look progressive but their zones are low-confidence estimates; not counted")
    if h["corners"] or a["corners"]:
        add("corners", "partial", "from tags only; not confirmed by the match sheet")
    no_shirt = sum(1 for e in evs if e.get("shirt") is None and e.get("type") != "gap")
    if no_shirt:
        add("players", "partial", f"{no_shirt} event(s) have no shirt number (player by position only or unknown), "
            "so player rows do not add up to team totals")
    return flags


def match_minutes(events: list[dict[str, Any]], lineup: dict[str, Any] | None) -> float:
    if lineup and lineup.get("match_minutes"):
        return float(lineup["match_minutes"])
    last = max((e["t_match_seconds"] for e in events), default=0.0)
    return float(max(90, math.ceil(last / 60.0)))


def _window(p: dict[str, Any], total: float) -> tuple[float, float] | None:
    on = p.get("on_minute")
    if on is None:
        if not p.get("starter", True):
            return None  # unused sub
        on = 0.0
    off = p.get("off_minute")
    return float(on), float(total if off is None else off)


def player_stats(
    events: list[dict[str, Any]], lineup: dict[str, Any] | None = None, *, confirmed_only: bool = False
) -> list[dict[str, Any]]:
    evs = usable_events(events, confirmed_only=confirmed_only)
    total = match_minutes(evs, lineup)
    people: dict[tuple[str, int], dict[str, Any]] = {}
    for p in (lineup or {}).get("players") or []:
        if p.get("team") in TEAMS and p.get("shirt") is not None:
            people[(p["team"], int(p["shirt"]))] = {**p, "_lineup": True}
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for e in evs:
        if e.get("shirt") is not None:
            key = (e["team"], int(e["shirt"]))
            grouped[key].append(e)
            people.setdefault(key, {"team": e["team"], "shirt": key[1], "name": e.get("player")})
            if not people[key].get("name") and e.get("player"):
                people[key]["name"] = e["player"]

    gk_types = {"save", "gk_pass", "goal_conceded"}
    for key, p in people.items():
        if not p.get("position"):
            p["position"] = "GK" if any(e["type"] in gk_types for e in grouped.get(key, [])) else None

    goals_by_team = {t: sorted(e["t_match_seconds"] / 60.0 for e in evs if e["type"] == "goal" and e["team"] == t) for t in TEAMS}
    gks_by_team = {t: [k for k, p in people.items() if k[0] == t and (p.get("position") or "").upper() == "GK"] for t in TEAMS}

    rows: list[dict[str, Any]] = []
    for key in sorted(people, key=lambda k: (TEAMS.index(k[0]), k[1])):
        p, mine = people[key], grouped.get(key, [])
        win = _window(p, total) if p.get("_lineup") else None
        minutes = round(max(0.0, win[1] - win[0]), 1) if win else None

        def n(etype: str, pred=lambda e: True) -> int:
            return sum(1 for e in mine if e["type"] == etype and pred(e))

        row: dict[str, Any] = {
            "team": key[0], "shirt": key[1], "name": p.get("name"),
            "position": p.get("position"), "minutes": minutes,
        }
        if (p.get("position") or "").upper() == "GK":
            opp_shots = [e for e in evs if e["type"] == "shot" and e["team"] == _other(key[0])]
            saves = sum(1 for e in mine if _is_save(e, opp_shots))
            opp_goals = goals_by_team[_other(key[0])]
            if win:
                conceded = sum(1 for m in opp_goals if win[0] <= m <= win[1])
            elif len(gks_by_team[key[0]]) == 1:
                conceded = len(opp_goals)
            else:
                conceded = None  # several keepers and no lineup minutes
            short = [e for e in mine if e["type"] == "gk_pass" and _a(e, "length") == "short"]
            long_ = [e for e in mine if e["type"] == "gk_pass" and _a(e, "length") == "long"]
            s_ok = sum(1 for e in short if _a(e, "completed") is True)
            l_ok = sum(1 for e in long_ if _a(e, "completed") is True)
            row.update({
                "role": "goalkeeper", "saves": saves, "conceded": conceded,
                "save_pct": _pct(saves, saves + conceded) if conceded is not None else None,
                "passes_short": len(short), "passes_short_completed": s_ok, "passes_short_accuracy_pct": _pct(s_ok, len(short)),
                "passes_long": len(long_), "passes_long_completed": l_ok, "passes_long_accuracy_pct": _pct(l_ok, len(long_)),
            })
        else:
            shots = [e for e in mine if e["type"] == "shot"]
            passes = [e for e in mine if is_pass(e)]
            done = sum(1 for e in passes if is_ok(e))
            prog_all = [e for e in mine if _prog_candidate(e) and is_progressive(e)]
            prog = [e for e in prog_all if not coords_estimated(e)]
            prog_ok = sum(1 for e in prog if is_ok(e))
            row.update({
                "role": "outfield", "goals": n("goal"),
                "assists": sum(1 for e in evs if e["type"] == "goal" and e["team"] == key[0]
                               and _a(e, "assist_shirt") is not None and int(_a(e, "assist_shirt")) == key[1]),
                "shots": len(shots),
                "shots_on_target": sum(1 for e in shots if _a(e, "on_target") is True),
                "xg": round(sum(float(_a(e, "xg") or 0.0) for e in shots), 2),
                "key_passes": n("pass", lambda e: _a(e, "key_pass") is True),
                "progressive_passes": len(prog), "progressive_passes_completed": prog_ok,
                "progressive_pass_pct": _pct(prog_ok, len(prog)),
                "progressive_passes_estimated": len(prog_all) - len(prog),
                "passes": len(passes), "passes_completed": done, "pass_accuracy_pct": _pct(done, len(passes)),
                "crosses": sum(1 for e in mine if event_code(e) == "CROSS"),
                "tackles": sum(1 for e in mine if event_code(e) == "TACKLE"),
                "interceptions": sum(1 for e in mine if event_code(e) == "INTERCEPT"),
                "balls_lost": n("ball_lost"),
                "aerials_won": n("aerial_duel", lambda e: _a(e, "won") is True),
                "aerials_lost": n("aerial_duel", lambda e: _a(e, "won") is False),
            })
        rows.append(row)
    return rows


def match_stats(events: list[dict[str, Any]], lineup: dict[str, Any] | None = None, *, confirmed_only: bool = False) -> dict[str, Any]:
    live = [e for e in events if e.get("review_status") != "rejected"]
    teams = team_stats(events, confirmed_only=confirmed_only)
    flags = stat_flags(events, teams, confirmed_only=confirmed_only)
    players = player_stats(events, lineup, confirmed_only=confirmed_only)
    if "players" in flags:
        for r in players:
            r["status"] = "partial"
            r["status_reason"] = flags["players"]["reasons"][0]
    return {
        "confirmed_only": confirmed_only,
        "events_counted": len(usable_events(events, confirmed_only=confirmed_only)),
        "pending_review": sum(1 for e in live if e.get("review_status") == "pending"),
        "events_without_team": sum(1 for e in live if e.get("team") not in TEAMS),
        "unattributed_player_events": sum(1 for e in usable_events(events, confirmed_only=confirmed_only) if e.get("shirt") is None),
        "footage_gaps": sum(1 for e in live if e.get("type") == "gap"),
        "match_minutes": match_minutes(live, lineup),
        "method": "direct counts of every logged event over the whole match; never extrapolated",
        "definitions": {"ppda": PPDA_DEFINITION, "progressive_passes": PROGRESSIVE_DEFINITION,
                        "possession_pct": "share of all passes attempted (PASS, GK_PASS, FK, GOALKICK, THROW)",
                        "passes": "PASS + GK_PASS + FK + GOALKICK + THROW; crosses and corners counted separately"},
        "stat_flags": flags,
        "teams": teams,
        "players": players,
    }


_PROG_PARTS = ("progressive_passes", "progressive_passes_completed", "progressive_pass_pct")


def _flag_cols(flags: dict[str, Any], metric: str) -> list[str]:
    f = flags.get(metric)
    return [f["status"], "; ".join(f["reasons"])] if f else ["counted", ""]


def team_csv(stats: dict[str, Any]) -> str:
    """metric,home,away,status,reason. status is counted / partial / estimated."""

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "home", "away", "status", "reason"])
    teams, flags = stats["teams"], stats.get("stat_flags") or {}
    for metric in teams["home"]:
        if metric in _PROG_PARTS[1:]:
            continue
        if metric == "progressive_passes":
            vals = [f"{teams[t]['progressive_passes']}/{teams[t]['progressive_passes_completed']}"
                    f" ({'' if teams[t]['progressive_pass_pct'] is None else teams[t]['progressive_pass_pct']}%)"
                    for t in TEAMS]
            w.writerow(["Progressive Passes (attempted/completed (success %))", *vals, *_flag_cols(flags, metric)])
            continue
        vals = [teams[t][metric] for t in TEAMS]
        vals = [";".join(f"{k}={v}" for k, v in x.items()) if isinstance(x, dict) else ("" if x is None else x) for x in vals]
        w.writerow([metric, *vals, *_flag_cols(flags, metric)])
    return buf.getvalue()


def player_csv(stats: dict[str, Any]) -> str:
    rows = stats["players"]
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols or ["team", "shirt"], restval="")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()
