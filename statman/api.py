"""FastAPI app: JSON API under /api plus the StatMan web UI."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from statman.compute import compute_match_stats
from statman.load import (
    DEFAULT_COMPETITION_ID,
    DEFAULT_GAME_ID,
    DEFAULT_SEASON_ID,
    list_demo_games,
    load_match,
)
from statman.season import (
    build_status,
    player_leaderboard,
    season_overview,
    start_build_async,
    team_page,
    tournament_table,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="StatMan match stats",
    version="0.2.0",
    description=(
        "Loads StatsBomb open-data matches, converts events to SPADL "
        "(socceraction), and returns possession, xG, passes, progressive passes, "
        "PPDA, tackles, interceptions, clearances, and aerials as JSON. "
        "Season endpoints aggregate a full competition into a tournament table, "
        "team match sheets, and player leaderboards."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


@app.get("/api")
def api_root() -> dict[str, Any]:
    return {
        "service": "statman",
        "docs": "/api/docs",
        "ui": "/",
        "season_ui": "/season",
        "endpoints": {
            "health": "/api/health",
            "demo_games": "/api/games/demo",
            "match_stats": f"/api/matches/{{game_id}}/stats  (default game_id={DEFAULT_GAME_ID})",
            "season_overview": "/api/seasons/{competition_id}/{season_id}",
            "season_build": "/api/seasons/{competition_id}/{season_id}/build",
            "season_table": "/api/seasons/{competition_id}/{season_id}/table",
            "season_team": "/api/seasons/{competition_id}/{season_id}/teams/{team_id}",
            "season_players": "/api/seasons/{competition_id}/{season_id}/players",
        },
        "default_game_id": DEFAULT_GAME_ID,
        "default_competition_id": DEFAULT_COMPETITION_ID,
        "default_season_id": DEFAULT_SEASON_ID,
        "default_match": "Belgium vs England, FIFA World Cup 2018 third place",
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/games/demo")
def demo_games(limit: int = Query(20, ge=1, le=64)) -> dict[str, Any]:
    try:
        games = list_demo_games(limit=limit)
    except Exception as exc:  # noqa: BLE001 - surface loader/network errors to the client
        raise HTTPException(status_code=502, detail=f"Failed to list open games: {exc}") from exc
    return {"competition": "FIFA World Cup 2018", "count": len(games), "games": games}


@app.get("/api/matches/{game_id}/stats")
def match_stats(game_id: int) -> dict[str, Any]:
    try:
        return _cached_stats(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to compute match stats: {exc}") from exc


@app.get("/api/matches/stats")
def default_match_stats() -> dict[str, Any]:
    """Convenience: Belgium–England World Cup 2018 (game 8657)."""
    return match_stats(DEFAULT_GAME_ID)


@app.get("/api/seasons/{competition_id}/{season_id}")
def api_season_overview(competition_id: int, season_id: int) -> dict[str, Any]:
    return season_overview(competition_id, season_id)


@app.post("/api/seasons/{competition_id}/{season_id}/build")
def api_season_build(
    competition_id: int,
    season_id: int,
    limit: int | None = Query(None, ge=1, le=128),
    force: bool = Query(False),
) -> dict[str, Any]:
    """Start (or resume) building stored match stats for a competition."""

    return start_build_async(competition_id, season_id, limit=limit, force=force)


@app.get("/api/seasons/{competition_id}/{season_id}/build")
def api_season_build_status(competition_id: int, season_id: int) -> dict[str, Any]:
    status = build_status()
    overview = season_overview(competition_id, season_id)
    return {"build": status, "season": overview}


@app.get("/api/seasons/{competition_id}/{season_id}/table")
def api_season_table(competition_id: int, season_id: int) -> dict[str, Any]:
    data = tournament_table(competition_id, season_id)
    if data.get("status") == "empty":
        raise HTTPException(
            status_code=404,
            detail="No stored matches yet. POST /build to load the competition.",
        )
    return data


@app.get("/api/seasons/{competition_id}/{season_id}/teams/{team_id}")
def api_season_team(competition_id: int, season_id: int, team_id: int) -> dict[str, Any]:
    data = team_page(team_id, competition_id, season_id)
    if not data.get("matches"):
        raise HTTPException(status_code=404, detail="Team not found in stored season data")
    return data


@app.get("/api/seasons/{competition_id}/{season_id}/players")
def api_season_players(
    competition_id: int,
    season_id: int,
    sort: str = Query("xg"),
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    data = player_leaderboard(competition_id, season_id, sort=sort, limit=limit)
    if data.get("matches_used", 0) == 0:
        raise HTTPException(
            status_code=404,
            detail="No stored matches yet. POST /build to load the competition.",
        )
    return data


def _page(name: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return FileResponse(path)


@app.get("/")
def ui() -> FileResponse:
    return _page("index.html")


@app.get("/season")
def ui_season() -> FileResponse:
    return _page("season.html")


@app.get("/season/team")
def ui_season_team() -> FileResponse:
    return _page("team.html")


@app.get("/season/players")
def ui_season_players() -> FileResponse:
    return _page("players.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@lru_cache(maxsize=8)
def _cached_stats(game_id: int) -> dict[str, Any]:
    bundle = load_match(game_id)
    return compute_match_stats(bundle)
