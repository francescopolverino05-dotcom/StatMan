"""Team and player stats from tagged events (match totals, no half split).

Definitions (documented so analysts can check the maths):

* possession_pct: team share of all attempted passes (``pass`` + ``gk_pass``).
* xg: sum of ``shot.xg``; shots without an xg are counted in ``xg_missing``.
* on/off target: blocked and missed shots are off target.
* shot_accuracy_pct: on target / shots.
* ppda: opponent passes in their own half / our tackles + interceptions +
  fouls in the opponent half. Uses event x (0..100 from the acting team's
  view, attacking toward x=100); events without x are left out and counted
  in ``ppda_events_without_x``.
* goals_conceded: the opponent's goals. save_pct: saves / (saves + conceded).
* shots_faced: all opponent shots; on_target_faced: opponent shots on target.
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


def team_stats(events: list[dict[str, Any]], *, confirmed_only: bool = False) -> dict[str, Any]:
    evs = usable_events(events, confirmed_only=confirmed_only)
    by: dict[str, list[dict[str, Any]]] = {t: [e for e in evs if e["team"] == t] for t in TEAMS}
    all_passes = sum(1 for e in evs if e["type"] in {"pass", "gk_pass"})
    out: dict[str, Any] = {}
    for team in TEAMS:
        mine, opp = by[team], by[_other(team)]

        def n(etype: str, pred=lambda e: True, src=mine) -> int:
            return sum(1 for e in src if e["type"] == etype and pred(e))

        shots = [e for e in mine if e["type"] == "shot"]
        on_t = sum(1 for e in shots if _a(e, "on_target") is True)
        passes = n("pass")
        completed = n("pass", lambda e: _a(e, "completed") is True)
        team_passes = passes + n("gk_pass")
        line_broken = Counter(_a(e, "line_broken") for e in mine if e["type"] == "pass" and _a(e, "line_broken"))

        opp_own_half = [e for e in opp if e["type"] in {"pass", "gk_pass"}]
        ppda_num = sum(1 for e in opp_own_half if e.get("x") is not None and e["x"] < 50)
        def_actions = [e for e in mine if e["type"] in {"tackle", "interception", "foul"}]
        ppda_den = sum(1 for e in def_actions if e.get("x") is not None and e["x"] >= 50)
        no_x = sum(1 for e in opp_own_half + def_actions if e.get("x") is None)

        saves = n("save")
        conceded = n("goal", src=opp)
        opp_shots = [e for e in opp if e["type"] == "shot"]
        gk_passes = [e for e in mine if e["type"] == "gk_pass"]
        gk_done = sum(1 for e in gk_passes if _a(e, "completed") is True)

        out[team] = {
            "goals": n("goal"),
            "possession_pct": _pct(team_passes, all_passes),
            "fouls": n("foul"),
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
            "passes": passes,
            "passes_completed": completed,
            "pass_accuracy_pct": _pct(completed, passes),
            "progressive_passes": n("pass", lambda e: _a(e, "progressive") is True),
            "line_broken": dict(sorted(line_broken.items())),
            "crosses": n("pass", lambda e: _a(e, "cross") is True),
            "tackles": n("tackle"),
            "interceptions": n("interception"),
            "ppda": round(ppda_num / ppda_den, 2) if ppda_den else None,
            "ppda_opponent_passes_own_half": ppda_num,
            "ppda_defensive_actions_opp_half": ppda_den,
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
            saves = n("save")
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
            passes = n("pass")
            done = n("pass", lambda e: _a(e, "completed") is True)
            row.update({
                "role": "outfield", "goals": n("goal"),
                "assists": sum(1 for e in evs if e["type"] == "goal" and e["team"] == key[0]
                               and _a(e, "assist_shirt") is not None and int(_a(e, "assist_shirt")) == key[1]),
                "shots": len(shots),
                "shots_on_target": sum(1 for e in shots if _a(e, "on_target") is True),
                "xg": round(sum(float(_a(e, "xg") or 0.0) for e in shots), 2),
                "key_passes": n("pass", lambda e: _a(e, "key_pass") is True),
                "progressive_passes": n("pass", lambda e: _a(e, "progressive") is True),
                "passes": passes, "passes_completed": done, "pass_accuracy_pct": _pct(done, passes),
                "crosses": n("pass", lambda e: _a(e, "cross") is True),
                "tackles": n("tackle"), "interceptions": n("interception"), "balls_lost": n("ball_lost"),
                "aerials_won": n("aerial_duel", lambda e: _a(e, "won") is True),
                "aerials_lost": n("aerial_duel", lambda e: _a(e, "won") is False),
            })
        rows.append(row)
    return rows


def match_stats(events: list[dict[str, Any]], lineup: dict[str, Any] | None = None, *, confirmed_only: bool = False) -> dict[str, Any]:
    live = [e for e in events if e.get("review_status") != "rejected"]
    return {
        "confirmed_only": confirmed_only,
        "events_counted": len(usable_events(events, confirmed_only=confirmed_only)),
        "pending_review": sum(1 for e in live if e.get("review_status") == "pending"),
        "events_without_team": sum(1 for e in live if e.get("team") not in TEAMS),
        "unattributed_player_events": sum(1 for e in usable_events(events, confirmed_only=confirmed_only) if e.get("shirt") is None),
        "match_minutes": match_minutes(live, lineup),
        "teams": team_stats(events, confirmed_only=confirmed_only),
        "players": player_stats(events, lineup, confirmed_only=confirmed_only),
    }


def team_csv(stats: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["metric", "home", "away"])
    teams = stats["teams"]
    for metric in teams["home"]:
        vals = [teams[t][metric] for t in TEAMS]
        vals = [";".join(f"{k}={v}" for k, v in x.items()) if isinstance(x, dict) else ("" if x is None else x) for x in vals]
        w.writerow([metric, *vals])
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
