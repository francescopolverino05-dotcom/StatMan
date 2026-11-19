"""Load a full open competition and aggregate tournament / team / player views."""

from __future__ import annotations

import threading
import time
from typing import Any

import pandas as pd

from statman.compute import compute_match_stats
from statman.load import (
    DEFAULT_COMPETITION_ID,
    DEFAULT_SEASON_ID,
    load_match,
)
from statman import store

# In-process build status for the UI poller.
_BUILD: dict[str, Any] = {
    "running": False,
    "competition_id": None,
    "season_id": None,
    "done": 0,
    "total": 0,
    "current_game_id": None,
    "error": None,
    "started_at": None,
    "finished_at": None,
}
_BUILD_LOCK = threading.Lock()


def build_status() -> dict[str, Any]:
    with _BUILD_LOCK:
        return dict(_BUILD)


def list_season_games(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> list[dict[str, Any]]:
    """List all open-data games in a competition/season (network)."""
    from socceraction.data.statsbomb import StatsBombLoader

    loader = StatsBombLoader(getter="remote", creds={"user": None, "passwd": None})
    games = loader.games(competition_id, season_id).sort_values("game_date")
    competitions = loader.competitions()
    comp_row = competitions[
        (competitions["competition_id"] == competition_id)
        & (competitions["season_id"] == season_id)
    ]
    competition_name = (
        str(comp_row.iloc[0]["competition_name"]) if not comp_row.empty else "Competition"
    )
    season_name = str(comp_row.iloc[0]["season_name"]) if not comp_row.empty else str(season_id)

    # Resolve team names from a few lineups
    name_map: dict[int, str] = {}
    out: list[dict[str, Any]] = []
    for row in games.itertuples(index=False):
        out.append(
            {
                "game_id": int(row.game_id),
                "game_date": str(row.game_date),
                "home_team_id": int(row.home_team_id),
                "away_team_id": int(row.away_team_id),
                "home_score": int(row.home_score) if pd.notna(row.home_score) else None,
                "away_score": int(row.away_score) if pd.notna(row.away_score) else None,
                "competition": competition_name,
                "season": season_name,
            }
        )

    for g in out[: min(len(out), 32)]:
        for tid in (g["home_team_id"], g["away_team_id"]):
            if tid in name_map:
                continue
            tdf = loader.teams(g["game_id"])
            for r in tdf.itertuples(index=False):
                name_map[int(r.team_id)] = str(r.team_name)
    for g in out:
        g["home_team"] = name_map.get(g["home_team_id"], str(g["home_team_id"]))
        g["away_team"] = name_map.get(g["away_team_id"], str(g["away_team_id"]))
    return out


def build_season(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
    *,
    limit: int | None = None,
    force: bool = False,
    progress_cb: Any | None = None,
) -> dict[str, Any]:
    """Compute and store per-match stats for every game in the season."""

    games = list_season_games(competition_id, season_id)
    if limit is not None:
        games = games[:limit]

    meta = {
        "competition_id": competition_id,
        "season_id": season_id,
        "competition": games[0]["competition"] if games else None,
        "season": games[0]["season"] if games else None,
        "status": "building",
        "games_total": len(games),
        "games_done": 0,
        "game_ids": [g["game_id"] for g in games],
        "errors": [],
    }
    store.write_meta(competition_id, season_id, meta)

    done = 0
    for game in games:
        game_id = int(game["game_id"])
        if progress_cb is not None:
            progress_cb(done, len(games), game_id)
        existing = store.load_match_stats(competition_id, season_id, game_id)
        if existing is not None and not force:
            done += 1
            meta["games_done"] = done
            store.write_meta(competition_id, season_id, meta)
            continue
        try:
            bundle = load_match(game_id)
            # Ensure competition labels are present even if loader omits them
            if not bundle.game.get("competition_name"):
                bundle.game["competition_name"] = game["competition"]
            if not bundle.game.get("season_name"):
                bundle.game["season_name"] = game["season"]
            payload = compute_match_stats(bundle)
            store.save_match(competition_id, season_id, game_id, payload)
        except Exception as exc:  # noqa: BLE001 - keep building remaining matches
            meta["errors"].append({"game_id": game_id, "error": str(exc)})
        done += 1
        meta["games_done"] = done
        store.write_meta(competition_id, season_id, meta)

    meta["status"] = "ready" if not meta["errors"] else "ready_with_errors"
    store.write_meta(competition_id, season_id, meta)
    if progress_cb is not None:
        progress_cb(done, len(games), None)
    return meta


def start_build_async(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
    *,
    limit: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Kick off ``build_season`` on a background thread."""

    with _BUILD_LOCK:
        if _BUILD["running"]:
            return dict(_BUILD)
        _BUILD.update(
            {
                "running": True,
                "competition_id": competition_id,
                "season_id": season_id,
                "done": 0,
                "total": 0,
                "current_game_id": None,
                "error": None,
                "started_at": time.time(),
                "finished_at": None,
            }
        )

    def _run() -> None:
        def on_progress(done: int, total: int, game_id: int | None) -> None:
            with _BUILD_LOCK:
                _BUILD["done"] = done
                _BUILD["total"] = total
                _BUILD["current_game_id"] = game_id

        try:
            build_season(
                competition_id,
                season_id,
                limit=limit,
                force=force,
                progress_cb=on_progress,
            )
        except Exception as exc:  # noqa: BLE001
            with _BUILD_LOCK:
                _BUILD["error"] = str(exc)
        finally:
            with _BUILD_LOCK:
                _BUILD["running"] = False
                _BUILD["finished_at"] = time.time()
                _BUILD["current_game_id"] = None

    threading.Thread(target=_run, name="statman-season-build", daemon=True).start()
    return build_status()


def season_overview(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, Any]:
    meta = store.read_meta(competition_id, season_id) or {
        "competition_id": competition_id,
        "season_id": season_id,
        "status": "empty",
        "games_total": 0,
        "games_done": 0,
    }
    stored = store.list_stored_game_ids(competition_id, season_id)
    meta = dict(meta)
    meta["stored_game_ids"] = stored
    meta["stored_count"] = len(stored)
    meta["build"] = build_status()
    return meta


def tournament_table(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, Any]:
    """Aggregate team stats across stored matches (tournament / league table)."""

    matches = store.iter_stored_matches(competition_id, season_id)
    if not matches:
        return {
            "competition_id": competition_id,
            "season_id": season_id,
            "status": "empty",
            "teams": [],
        }

    teams: dict[int, dict[str, Any]] = {}

    def bucket(team_id: int, team_name: str) -> dict[str, Any]:
        if team_id not in teams:
            teams[team_id] = {
                "team_id": team_id,
                "team_name": team_name,
                "played": 0,
                "wins": 0,
                "draws": 0,
                "losses": 0,
                "goals_for": 0,
                "goals_against": 0,
                "goal_diff": 0,
                "points": 0,
                "xg_for": 0.0,
                "xg_against": 0.0,
                "possession_sum": 0.0,
                "possession_n": 0,
                "ppda_sum": 0.0,
                "ppda_n": 0,
                "progressive_passes": 0,
                "passes_attempted": 0,
                "passes_completed": 0,
                "shots": 0,
                "tackles": 0,
                "interceptions": 0,
                "clearances": 0,
                "aerials_won": 0,
                "aerials_lost": 0,
            }
        return teams[team_id]

    for payload in matches:
        match = payload["match"]
        by_id = {int(t["team_id"]): t for t in payload["teams"]}
        home_id = int(match["home_team_id"])
        away_id = int(match["away_team_id"])
        home_score = int(match.get("home_score") or 0)
        away_score = int(match.get("away_score") or 0)
        home = by_id.get(home_id)
        away = by_id.get(away_id)
        if home is None or away is None:
            continue

        pairs = (
            (home, away, home_score, away_score),
            (away, home, away_score, home_score),
        )
        for us, them, gf, ga in pairs:
            row = bucket(int(us["team_id"]), str(us["team_name"]))
            row["played"] += 1
            row["goals_for"] += gf
            row["goals_against"] += ga
            if gf > ga:
                row["wins"] += 1
                row["points"] += 3
            elif gf == ga:
                row["draws"] += 1
                row["points"] += 1
            else:
                row["losses"] += 1
            row["xg_for"] += float(us.get("xg") or 0.0)
            row["xg_against"] += float(them.get("xg") or 0.0)
            if us.get("possession_pct") is not None:
                row["possession_sum"] += float(us["possession_pct"])
                row["possession_n"] += 1
            if us.get("ppda") is not None:
                row["ppda_sum"] += float(us["ppda"])
                row["ppda_n"] += 1
            row["progressive_passes"] += int(us.get("progressive_passes") or 0)
            row["passes_attempted"] += int(us.get("passes_attempted") or 0)
            row["passes_completed"] += int(us.get("passes_completed") or 0)
            row["shots"] += int(us.get("shots") or 0)
            row["tackles"] += int(us.get("tackles") or 0)
            row["interceptions"] += int(us.get("interceptions") or 0)
            row["clearances"] += int(us.get("clearances") or 0)
            row["aerials_won"] += int(us.get("aerials_won") or 0)
            row["aerials_lost"] += int(us.get("aerials_lost") or 0)

    table = []
    for row in teams.values():
        row["goal_diff"] = row["goals_for"] - row["goals_against"]
        row["xg_for"] = round(row["xg_for"], 3)
        row["xg_against"] = round(row["xg_against"], 3)
        row["xg_diff"] = round(row["xg_for"] - row["xg_against"], 3)
        row["possession_pct"] = (
            round(row["possession_sum"] / row["possession_n"], 1)
            if row["possession_n"]
            else None
        )
        row["ppda"] = (
            round(row["ppda_sum"] / row["ppda_n"], 3) if row["ppda_n"] else None
        )
        row["pass_accuracy"] = (
            round(100.0 * row["passes_completed"] / row["passes_attempted"], 1)
            if row["passes_attempted"]
            else None
        )
        # Drop running sums from the public row
        for key in ("possession_sum", "possession_n", "ppda_sum", "ppda_n"):
            row.pop(key, None)
        table.append(row)

    table.sort(
        key=lambda r: (
            -r["points"],
            -r["goal_diff"],
            -r["goals_for"],
            -r["xg_diff"],
            r["team_name"],
        )
    )
    meta = store.read_meta(competition_id, season_id) or {}
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "competition": meta.get("competition"),
        "season": meta.get("season"),
        "status": meta.get("status", "ready"),
        "matches_used": len(matches),
        "teams": table,
    }


def team_page(
    team_id: int,
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
) -> dict[str, Any]:
    """Match-by-match sheet for one team."""

    matches = store.iter_stored_matches(competition_id, season_id)
    rows: list[dict[str, Any]] = []
    team_name = None
    for payload in matches:
        match = payload["match"]
        us = next((t for t in payload["teams"] if int(t["team_id"]) == team_id), None)
        if us is None:
            continue
        team_name = us["team_name"]
        home = int(match["home_team_id"]) == team_id
        gf = match["home_score"] if home else match["away_score"]
        ga = match["away_score"] if home else match["home_score"]
        opponent = match["away_team"] if home else match["home_team"]
        rows.append(
            {
                "game_id": match["game_id"],
                "game_date": match.get("game_date"),
                "venue": "H" if home else "A",
                "opponent": opponent,
                "score_for": gf,
                "score_against": ga,
                "result": (
                    "W"
                    if (gf or 0) > (ga or 0)
                    else "D"
                    if (gf or 0) == (ga or 0)
                    else "L"
                ),
                "xg": us.get("xg"),
                "possession_pct": us.get("possession_pct"),
                "ppda": us.get("ppda"),
                "progressive_passes": us.get("progressive_passes"),
                "pass_accuracy": us.get("pass_accuracy"),
                "shots": us.get("shots"),
                "tackles": us.get("tackles"),
                "interceptions": us.get("interceptions"),
                "aerials_won": us.get("aerials_won"),
                "aerials_lost": us.get("aerials_lost"),
            }
        )

    if not rows:
        return {
            "team_id": team_id,
            "team_name": None,
            "matches": [],
            "status": "empty",
        }

    table = tournament_table(competition_id, season_id)
    summary = next((t for t in table["teams"] if int(t["team_id"]) == team_id), None)
    meta = store.read_meta(competition_id, season_id) or {}
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "competition": meta.get("competition"),
        "season": meta.get("season"),
        "team_id": team_id,
        "team_name": team_name,
        "summary": summary,
        "matches": rows,
    }


def player_leaderboard(
    competition_id: int = DEFAULT_COMPETITION_ID,
    season_id: int = DEFAULT_SEASON_ID,
    *,
    sort: str = "xg",
    limit: int = 40,
) -> dict[str, Any]:
    """Aggregate player stats across stored matches."""

    matches = store.iter_stored_matches(competition_id, season_id)
    players: dict[int, dict[str, Any]] = {}
    for payload in matches:
        for p in payload.get("players", []):
            pid = int(p["player_id"])
            row = players.get(pid)
            if row is None:
                row = {
                    "player_id": pid,
                    "player_name": p.get("player_name"),
                    "team_id": p.get("team_id"),
                    "team_name": p.get("team_name"),
                    "matches": 0,
                    "xg": 0.0,
                    "goals": 0,
                    "shots": 0,
                    "passes_attempted": 0,
                    "passes_completed": 0,
                    "progressive_passes": 0,
                    "tackles": 0,
                    "interceptions": 0,
                    "clearances": 0,
                    "aerials_won": 0,
                    "aerials_lost": 0,
                }
                players[pid] = row
            row["matches"] += 1
            row["player_name"] = p.get("player_name") or row["player_name"]
            row["team_name"] = p.get("team_name") or row["team_name"]
            row["xg"] += float(p.get("xg") or 0.0)
            row["goals"] += int(p.get("goals") or 0)
            row["shots"] += int(p.get("shots") or 0)
            row["passes_attempted"] += int(p.get("passes_attempted") or 0)
            row["passes_completed"] += int(p.get("passes_completed") or 0)
            row["progressive_passes"] += int(p.get("progressive_passes") or 0)
            row["tackles"] += int(p.get("tackles") or 0)
            row["interceptions"] += int(p.get("interceptions") or 0)
            row["clearances"] += int(p.get("clearances") or 0)
            row["aerials_won"] += int(p.get("aerials_won") or 0)
            row["aerials_lost"] += int(p.get("aerials_lost") or 0)

    sort_keys = {
        "xg": lambda r: (-r["xg"], -r["shots"], r["player_name"] or ""),
        "progressive_passes": lambda r: (
            -r["progressive_passes"],
            -r["passes_attempted"],
            r["player_name"] or "",
        ),
        "goals": lambda r: (-r["goals"], -r["xg"], r["player_name"] or ""),
        "tackles": lambda r: (-r["tackles"], -r["interceptions"], r["player_name"] or ""),
        "interceptions": lambda r: (
            -r["interceptions"],
            -r["tackles"],
            r["player_name"] or "",
        ),
        "aerials_won": lambda r: (-r["aerials_won"], -r["aerials_lost"], r["player_name"] or ""),
    }
    key_fn = sort_keys.get(sort, sort_keys["xg"])
    rows = list(players.values())
    for row in rows:
        row["xg"] = round(row["xg"], 3)
        row["pass_accuracy"] = (
            round(100.0 * row["passes_completed"] / row["passes_attempted"], 1)
            if row["passes_attempted"]
            else None
        )
    rows.sort(key=key_fn)
    meta = store.read_meta(competition_id, season_id) or {}
    return {
        "competition_id": competition_id,
        "season_id": season_id,
        "competition": meta.get("competition"),
        "season": meta.get("season"),
        "sort": sort if sort in sort_keys else "xg",
        "matches_used": len(matches),
        "players": rows[: max(1, min(limit, 200))],
    }
