"""FastAPI app: load one open match → compute stats → JSON."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from statman.compute import compute_match_stats
from statman.load import DEFAULT_GAME_ID, list_demo_games, load_match

app = FastAPI(
    title="StatMan match stats",
    version="0.1.0",
    description=(
        "Loads one StatsBomb open-data match, converts events to SPADL "
        "(socceraction), and returns possession, xG, passes, progressive passes, "
        "PPDA, tackles, interceptions, clearances, and aerials as JSON."
    ),
)


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "statman",
        "docs": "/docs",
        "endpoints": {
            "health": "/health",
            "demo_games": "/games/demo",
            "match_stats": f"/matches/{{game_id}}/stats  (default game_id={DEFAULT_GAME_ID})",
        },
        "default_game_id": DEFAULT_GAME_ID,
        "default_match": "Belgium vs England, FIFA World Cup 2018 third place",
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/games/demo")
def demo_games(limit: int = Query(20, ge=1, le=64)) -> dict[str, Any]:
    try:
        games = list_demo_games(limit=limit)
    except Exception as exc:  # noqa: BLE001 - surface loader/network errors to the client
        raise HTTPException(status_code=502, detail=f"Failed to list open games: {exc}") from exc
    return {"competition": "FIFA World Cup 2018", "count": len(games), "games": games}


@app.get("/matches/{game_id}/stats")
def match_stats(game_id: int) -> dict[str, Any]:
    try:
        return _cached_stats(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to compute match stats: {exc}") from exc


@app.get("/matches/stats")
def default_match_stats() -> dict[str, Any]:
    """Convenience: Belgium–England World Cup 2018 (game 8657)."""
    return match_stats(DEFAULT_GAME_ID)


@lru_cache(maxsize=8)
def _cached_stats(game_id: int) -> dict[str, Any]:
    bundle = load_match(game_id)
    return compute_match_stats(bundle)
