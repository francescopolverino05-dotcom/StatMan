"""FastAPI app: JSON API under /api plus the StatMan web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.concurrency import run_in_threadpool

from statman import persistence

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from statman.compute import compute_match_stats
from statman.event_import import get_import, import_events_auto, list_imports
from statman.load import (
    DEFAULT_COMPETITION_ID,
    DEFAULT_GAME_ID,
    DEFAULT_SEASON_ID,
    list_demo_games,
    load_match,
)
from statman.maps import map_events_for_game, render_map_png
from statman.season import (
    build_status,
    player_leaderboard,
    season_overview,
    start_build_async,
    team_page,
    tournament_table,
)
import json

from statman.packages import (
    MAX_FILE_BYTES,
    create_package,
    delete_package,
    get_package,
    list_packages,
    players_csv,
    shots_csv,
    team_csv,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def _lifespan(_app: Any):
    # Postgres (DATABASE_URL): run migrations, restore JSON to disk, start sync.
    persistence.bootstrap()
    try:
        yield
    finally:
        persistence.shutdown()

app = FastAPI(
    title="StatMan match stats",
    version="1.0.0",
    description=(
        "Stats viewer + exporter. Load a stats package (team CSV + players CSV, "
        "optional HTML report / shots CSV) and view/export it, or load StatsBomb "
        "open-data / event JSON (SPADL via socceraction) for possession, xG, passes, "
        "progressive passes, PPDA, tackles, interceptions, clearances and aerials. "
        "There is no tagging in this app."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=_lifespan,
)


@app.middleware("http")
async def _persist_after_request(request: Request, call_next: Any) -> Any:
    response = await call_next(request)
    if persistence.postgres_enabled() and request.method not in ("GET", "HEAD", "OPTIONS"):
        await run_in_threadpool(persistence.sync_all)
    return response


@app.get("/api/storage")
def api_storage() -> dict[str, Any]:
    return persistence.storage_status()


@app.get("/api")
def api_root() -> dict[str, Any]:
    return {
        "service": "statman",
        "mode": "stats viewer + exporter (no tagging)",
        "docs": "/api/docs",
        "ui": "/",
        "viewer_ui": "/",
        "demo_ui": "/demo",
        "season_ui": "/season",
        "import_ui": "/import",
        "endpoints": {
            "health": "/api/health",
            "packages": "GET|POST /api/packages  (load a stats package: team CSV + players CSV [+ HTML, shots CSV])",
            "package": "/api/packages/{package_id}",
            "package_team_csv": "/api/packages/{package_id}/team.csv",
            "package_players_csv": "/api/packages/{package_id}/players.csv",
            "package_shots_csv": "/api/packages/{package_id}/shots.csv",
            "package_report": "/api/packages/{package_id}/report.html",
            "package_json": "/api/packages/{package_id}/package.json",
            "demo_games": "/api/games/demo",
            "match_stats": f"/api/matches/{{game_id}}/stats  (default game_id={DEFAULT_GAME_ID})",
            "match_maps": "/api/matches/{game_id}/maps",
            "match_map_png": "/api/matches/{game_id}/maps/{kind}.png  (shots|progressive|defence)",
            "season_overview": "/api/seasons/{competition_id}/{season_id}",
            "season_build": "/api/seasons/{competition_id}/{season_id}/build",
            "season_table": "/api/seasons/{competition_id}/{season_id}/table",
            "season_team": "/api/seasons/{competition_id}/{season_id}/teams/{team_id}",
            "season_players": "/api/seasons/{competition_id}/{season_id}/players",
            "event_import": "/api/imports",
            "event_import_job": "/api/imports/{import_id}",
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


@app.get("/api/matches/{game_id}/maps")
def match_maps(game_id: int) -> dict[str, Any]:
    """JSON coordinates for shot / progressive-pass / defence pitch maps."""

    try:
        return map_events_for_game(game_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to build map events: {exc}") from exc


@app.get("/api/matches/{game_id}/maps/{kind}.png")
def match_map_png(
    game_id: int,
    kind: str,
    team_id: int | None = Query(None),
) -> Response:
    """PNG pitch map: ``shots``, ``progressive``, or ``defence``."""

    allowed: set[str] = {"shots", "progressive", "defence"}
    if kind not in allowed:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown map kind '{kind}'. Use one of: {sorted(allowed)}",
        )
    try:
        png = render_map_png(game_id, kind=kind, team_id=team_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to render map: {exc}") from exc
    return Response(content=png, media_type="image/png")


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
@app.get("/viewer")
def ui() -> FileResponse:
    """Stats viewer: load a stats package (CSV + HTML) and view / export it."""
    return _page("index.html")


@app.get("/demo")
def ui_demo() -> FileResponse:
    """Legacy World Cup open-data demo (gold-standard catalog shape)."""
    return _page("demo.html")


@app.get("/season")
def ui_season() -> FileResponse:
    return _page("season.html")


@app.get("/season/team")
def ui_season_team() -> FileResponse:
    return _page("team.html")


@app.get("/season/players")
def ui_season_players() -> FileResponse:
    return _page("players.html")


@app.get("/import")
def ui_import() -> FileResponse:
    return _page("import.html")

@app.get("/api/packages")
def api_packages(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    rows = list_packages(limit=limit)
    return {"count": len(rows), "packages": rows}


@app.post("/api/packages")
async def api_package_create(
    files: list[UploadFile] = File(
        ...,
        description="Package files: *_team.csv, *_players.csv, optional *_stats.html, *_shots.csv, stats.json",
    ),
    title: str | None = Form(None),
) -> dict[str, Any]:
    """Load a stats package (team CSV + players CSV + optional HTML report / shots CSV)."""
    loaded: list[tuple[str, bytes]] = []
    for f in files:
        if not f.filename:
            continue
        data = await f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} is larger than {MAX_FILE_BYTES // 1_000_000} MB")
        loaded.append((f.filename, data))
    try:
        return create_package(loaded, title=title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/packages/{package_id}")
def api_package_get(package_id: str) -> dict[str, Any]:
    pkg = get_package(package_id, full=False)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"Unknown package_id={package_id}")
    return pkg


@app.delete("/api/packages/{package_id}")
def api_package_delete(package_id: str) -> dict[str, Any]:
    if not delete_package(package_id):
        raise HTTPException(status_code=404, detail=f"Unknown package_id={package_id}")
    return {"deleted": package_id}


def _package_or_404(package_id: str) -> dict[str, Any]:
    pkg = get_package(package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail=f"Unknown package_id={package_id}")
    return pkg


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/packages/{package_id}/team.csv")
def api_package_team_csv(package_id: str) -> Response:
    pkg = _package_or_404(package_id)
    return _csv_response(team_csv(pkg), f"{pkg['slug']}_team.csv")


@app.get("/api/packages/{package_id}/players.csv")
def api_package_players_csv(package_id: str) -> Response:
    pkg = _package_or_404(package_id)
    if not pkg.get("players"):
        raise HTTPException(status_code=404, detail="This package has no players table")
    return _csv_response(players_csv(pkg), f"{pkg['slug']}_players.csv")


@app.get("/api/packages/{package_id}/shots.csv")
def api_package_shots_csv(package_id: str) -> Response:
    pkg = _package_or_404(package_id)
    if not pkg.get("shots"):
        raise HTTPException(status_code=404, detail="This package has no shots table")
    return _csv_response(shots_csv(pkg), f"{pkg['slug']}_shots.csv")


@app.get("/api/packages/{package_id}/package.json")
def api_package_json(package_id: str) -> Response:
    pkg = _package_or_404(package_id)
    return Response(
        json.dumps({k: v for k, v in pkg.items() if k != "report_html"}, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{pkg["slug"]}_package.json"'},
    )


@app.get("/api/packages/{package_id}/report.html")
def api_package_report(package_id: str, download: bool = Query(False)) -> Response:
    """The original HTML report, served sandboxed (no scripts, no network)."""
    pkg = _package_or_404(package_id)
    html = pkg.get("report_html")
    if not html:
        raise HTTPException(status_code=404, detail="This package has no HTML report")
    headers = {
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:",
    }
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{pkg["slug"]}_stats.html"'
    return Response(html, media_type="text/html; charset=utf-8", headers=headers)




@app.get("/api/imports")
def api_imports(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    rows = list_imports(limit=limit)
    return {"count": len(rows), "imports": rows}


@app.post("/api/imports")
async def api_import_events(
    events: UploadFile = File(
        ...,
        description="StatsBomb events JSON (recommended) or Opta F24 JSON (partial catalog)",
    ),
    lineups: UploadFile | None = File(None, description="Optional StatsBomb lineups JSON"),
    match: UploadFile | None = File(None, description="Optional StatsBomb match JSON"),
    game_id: int | None = Form(None),
    home_team_id: int | None = Form(None),
) -> dict[str, Any]:
    """Import event JSON. Prefer StatsBomb for the full locked sheet; Opta is partial."""
    if not events.filename:
        raise HTTPException(status_code=400, detail="Missing events filename")
    try:
        result = import_events_auto(
            events.file,
            events.filename,
            lineups_file=lineups.file if lineups and lineups.filename else None,
            lineups_filename=lineups.filename if lineups else None,
            match_file=match.file if match and match.filename else None,
            match_filename=match.filename if match else None,
            game_id=game_id,
            home_team_id=home_team_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Import failed: {exc}") from exc
    return result


@app.get("/api/imports/{import_id}")
def api_import_get(import_id: str) -> dict[str, Any]:
    stats = get_import(import_id)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"Unknown import_id={import_id}")
    return {"import_id": import_id, "stats": stats}


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(WEB_DIR / "assets" / "favicon.ico", media_type="image/x-icon")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@lru_cache(maxsize=8)
def _cached_stats(game_id: int) -> dict[str, Any]:
    bundle = load_match(game_id)
    return compute_match_stats(bundle)
