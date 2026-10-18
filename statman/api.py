"""FastAPI app: JSON API under /api plus the StatMan web UI."""

from __future__ import annotations

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
from statman.match_pack import (
    append_pack_video_chunk,
    attach_formation,
    attach_video_bytes,
    cancel_pack_analyze,
    compute_pack,
    create_pack,
    example_facts,
    finish_pack_video,
    get_pack,
    import_film_job,
    import_matching_film_job,
    init_pack_video,
    list_packs,
    put_facts,
    put_facts_file,
    reconcile_pack,
    start_pack_analyze,
    start_phase3,
    cancel_phase3,
    start_phase4,
    start_phase5,
    start_phase6,
    start_phase7,
    start_phase8,
)
from statman.match_pack.phase3 import refresh_team_splits
from statman.video import (
    abort_upload,
    append_upload_chunk,
    cancel_job,
    finish_chunked_upload,
    get_job,
    init_chunked_upload,
    list_jobs,
    start_job,
    upload_video,
)
from statman.video.detector import yolo_status
from statman.video.pipeline import DEFAULT_CHUNK_BYTES, DEFAULT_SAMPLE_FPS

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="StatMan match stats",
    version="0.6.0",
    description=(
        "Loads StatsBomb open-data matches, converts events to SPADL "
        "(socceraction), and returns possession, xG, passes, progressive passes, "
        "PPDA, tackles, interceptions, clearances, and aerials as JSON. "
        "Match-pack Phase 1: facts. Phase 2: film tags. Phase 3: kit tracking / "
        "possession. Phase 4: rescored approximate shots. Phase 5: approximate SoT "
        "(goalmouth/save + deflection/corner). Phase 6: GK shots faced / saves from "
        "SoT. Phase 7: pass completion + tackle rescore. Phase 8: progressive "
        "passes, aerials, interceptions, clearances. xG and PPDA stay pending."
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
        "video_ui": "/video",
        "match_pack_ui": "/match-pack",
        "import_ui": "/import",
        "endpoints": {
            "health": "/api/health",
            "demo_games": "/api/games/demo",
            "match_stats": f"/api/matches/{{game_id}}/stats  (default game_id={DEFAULT_GAME_ID})",
            "match_maps": "/api/matches/{game_id}/maps",
            "match_map_png": "/api/matches/{game_id}/maps/{kind}.png  (shots|progressive|defence)",
            "season_overview": "/api/seasons/{competition_id}/{season_id}",
            "season_build": "/api/seasons/{competition_id}/{season_id}/build",
            "season_table": "/api/seasons/{competition_id}/{season_id}/table",
            "season_team": "/api/seasons/{competition_id}/{season_id}/teams/{team_id}",
            "season_players": "/api/seasons/{competition_id}/{season_id}/players",
            "video_upload": "/api/video/jobs",
            "video_upload_init": "POST /api/video/uploads",
            "video_upload_chunk": "PUT /api/video/uploads/{job_id}/chunk",
            "video_upload_finish": "POST /api/video/uploads/{job_id}/finish",
            "video_job": "/api/video/jobs/{job_id}",
            "video_cancel": "/api/video/jobs/{job_id}/cancel",
            "video_detector": "/api/video/detector",
            "event_import": "/api/imports",
            "event_import_job": "/api/imports/{import_id}",
            "match_packs": "/api/match-packs",
            "match_pack": "/api/match-packs/{pack_id}",
            "match_pack_facts": "PUT /api/match-packs/{pack_id}/facts",
            "match_pack_formation": "POST /api/match-packs/{pack_id}/formation",
            "match_pack_video": "POST /api/match-packs/{pack_id}/video/init",
            "match_pack_compute": "POST /api/match-packs/{pack_id}/compute",
            "match_pack_analyze": "POST /api/match-packs/{pack_id}/analyze",
            "match_pack_analyze_import": "POST /api/match-packs/{pack_id}/analyze/import",
            "match_pack_reconcile": "POST /api/match-packs/{pack_id}/reconcile",
            "match_pack_phase3": "POST /api/match-packs/{pack_id}/phase3",
            "match_pack_phase4": "POST /api/match-packs/{pack_id}/phase4",
            "match_pack_phase5": "POST /api/match-packs/{pack_id}/phase5",
            "match_pack_phase6": "POST /api/match-packs/{pack_id}/phase6",
            "match_pack_phase7": "POST /api/match-packs/{pack_id}/phase7",
            "match_pack_phase8": "POST /api/match-packs/{pack_id}/phase8",
            "match_pack_example_facts": "/api/match-packs/example-facts",
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


@app.get("/video")
def ui_video() -> FileResponse:
    return _page("video.html")


@app.get("/import")
def ui_import() -> FileResponse:
    return _page("import.html")


@app.get("/match-pack")
def ui_match_pack() -> FileResponse:
    return _page("match-pack.html")


@app.get("/api/video/detector")
def api_video_detector() -> dict[str, Any]:
    """Report detector backend; loads YOLO on first call so the UI can show readiness."""
    return yolo_status(ensure_loaded=True)


@app.get("/api/video/jobs")
def api_video_jobs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    jobs = list_jobs(limit=limit)
    return {"count": len(jobs), "jobs": jobs}


@app.post("/api/video/uploads")
async def api_video_upload_init(
    filename: str = Form(...),
    size_bytes: int = Form(..., ge=1),
) -> dict[str, Any]:
    """Start a resumable chunked upload for a full-match video."""
    try:
        return init_chunked_upload(filename, size_bytes, chunk_bytes=DEFAULT_CHUNK_BYTES)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/video/uploads/{job_id}/chunk")
async def api_video_upload_chunk(
    job_id: str,
    request: Request,
    offset: int = Query(..., ge=0),
) -> dict[str, Any]:
    """Append one binary chunk (raw body) at the given byte offset."""
    data = await request.body()
    try:
        return append_upload_chunk(job_id, data, offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/video/uploads/{job_id}/finish")
def api_video_upload_finish(
    job_id: str,
    sample_fps: float = Query(DEFAULT_SAMPLE_FPS, ge=0.2, le=2.0),
    auto_start: bool = Query(True),
) -> dict[str, Any]:
    """Finalize a chunked upload and optionally start approximate spotting."""
    try:
        return finish_chunked_upload(job_id, sample_fps=sample_fps, auto_start=auto_start)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/video/uploads/{job_id}")
def api_video_upload_abort(job_id: str) -> dict[str, Any]:
    """Abort an in-progress chunked upload."""
    try:
        return abort_upload(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/video/jobs")
async def api_video_upload(
    file: UploadFile = File(...),
    sample_fps: float = Query(DEFAULT_SAMPLE_FPS, ge=0.2, le=2.0),
    auto_start: bool = Query(True),
) -> dict[str, Any]:
    """One-shot upload (small files). Prefer chunked ``/api/video/uploads`` for full matches."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    try:
        meta = upload_video(file.file, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if auto_start:
        meta = start_job(meta["job_id"], sample_fps=sample_fps)
    return meta


@app.post("/api/video/jobs/{job_id}/start")
def api_video_start(
    job_id: str,
    sample_fps: float = Query(DEFAULT_SAMPLE_FPS, ge=0.2, le=2.0),
) -> dict[str, Any]:
    try:
        return start_job(job_id, sample_fps=sample_fps)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/video/jobs/{job_id}/cancel")
def api_video_cancel(job_id: str) -> dict[str, Any]:
    """Cancel a queued or running full-match spotting job."""
    try:
        return cancel_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/video/jobs/{job_id}")
def api_video_job(
    job_id: str,
    include_timeline: bool = Query(True),
) -> dict[str, Any]:
    job = get_job(job_id, include_timeline=include_timeline)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job_id={job_id}")
    return job


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


@app.get("/api/match-packs/example-facts")
def api_match_pack_example_facts() -> dict[str, Any]:
    """Example match-facts JSON (Belgium–England style) for the Phase-1 UI."""
    return example_facts()


@app.get("/api/match-packs")
def api_match_packs(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    packs = list_packs(limit=limit)
    return {"count": len(packs), "packs": packs}


@app.post("/api/match-packs")
def api_match_pack_create(
    title: str | None = Form(None),
    home_team: str | None = Form(None),
    away_team: str | None = Form(None),
) -> dict[str, Any]:
    return create_pack(title=title, home_team=home_team, away_team=away_team)


@app.get("/api/match-packs/{pack_id}")
def api_match_pack_get(pack_id: str) -> dict[str, Any]:
    meta = get_pack(pack_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown pack_id={pack_id}")
    return meta


@app.put("/api/match-packs/{pack_id}/facts")
async def api_match_pack_facts(pack_id: str, request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    try:
        return put_facts(pack_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/facts/file")
async def api_match_pack_facts_file(
    pack_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Upload a UTF-8 match-facts .json file. Bad files do not wipe prior facts."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing facts filename")
    name = file.filename.lower()
    if not (name.endswith(".json") or name.endswith(".txt")):
        raise HTTPException(
            status_code=400,
            detail="Facts upload must be a .json file (UTF-8 match-facts schema).",
        )
    try:
        return put_facts_file(pack_id, file.file, file.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/formation")
async def api_match_pack_formation(
    pack_id: str,
    side: str = Form(..., description="home or away"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing formation filename")
    try:
        return attach_formation(pack_id, side, file.file, file.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/video")
async def api_match_pack_video_oneshot(
    pack_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """One-shot video attach (small files / tests). Prefer chunked init/chunk/finish."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing video filename")
    try:
        return attach_video_bytes(pack_id, file.file, file.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/video/init")
async def api_match_pack_video_init(
    pack_id: str,
    filename: str = Form(...),
    size_bytes: int = Form(..., ge=1),
) -> dict[str, Any]:
    try:
        return init_pack_video(
            pack_id, filename, size_bytes, chunk_bytes=DEFAULT_CHUNK_BYTES
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/match-packs/{pack_id}/video/chunk")
async def api_match_pack_video_chunk(
    pack_id: str,
    request: Request,
    offset: int = Query(..., ge=0),
) -> dict[str, Any]:
    data = await request.body()
    try:
        return append_pack_video_chunk(pack_id, data, offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/video/finish")
def api_match_pack_video_finish(pack_id: str) -> dict[str, Any]:
    try:
        return finish_pack_video(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/compute")
def api_match_pack_compute(pack_id: str) -> dict[str, Any]:
    """Build the Phase-1 fact-sourced sheet (goals/cards/subs/set pieces/lineups)."""
    try:
        return compute_pack(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/analyze")
def api_match_pack_analyze(
    pack_id: str,
    sample_fps: float = Query(0.5, ge=0.05, le=2.0),
    reuse_matching_job: bool = Query(True),
) -> dict[str, Any]:
    """Phase 2: spot film tags on the pack video (or import a matching /video job)."""
    try:
        return start_pack_analyze(
            pack_id,
            sample_fps=sample_fps,
            reuse_matching_job=reuse_matching_job,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/analyze/import")
def api_match_pack_analyze_import(
    pack_id: str,
    video_job_id: str | None = Query(None),
) -> dict[str, Any]:
    """Import film tags from a finished /video job (or auto-match by filename)."""
    try:
        if video_job_id:
            return import_film_job(pack_id, video_job_id)
        return import_matching_film_job(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/analyze/cancel")
def api_match_pack_analyze_cancel(pack_id: str) -> dict[str, Any]:
    try:
        return cancel_pack_analyze(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/reconcile")
def api_match_pack_reconcile(
    pack_id: str,
    promote: bool = Query(
        True,
        description="Write corrected film summary into facts.film_corrected",
    ),
) -> dict[str, Any]:
    """Anchor film Goal tags to fact goals and promote a corrected summary into facts."""
    try:
        return reconcile_pack(pack_id, promote=promote)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase3")
def api_match_pack_phase3(
    pack_id: str,
    sample_fps: float = Query(0.25, ge=0.05, le=1.0),
    max_duration_sec: float | None = Query(
        None,
        ge=30,
        le=150 * 60,
        description="Optional cap for smoke tests / partial runs",
    ),
    start_sec: float = Query(0.0, ge=0.0, le=150 * 60),
) -> dict[str, Any]:
    """Phase 3: kit-colour tracking → possession + home/away film-tag splits."""
    try:
        return start_phase3(
            pack_id,
            sample_fps=sample_fps,
            max_duration_sec=max_duration_sec,
            start_sec=start_sec,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase3/cancel")
def api_match_pack_phase3_cancel(pack_id: str) -> dict[str, Any]:
    try:
        return cancel_phase3(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase3/refresh-splits")
def api_match_pack_phase3_refresh_splits(pack_id: str) -> dict[str, Any]:
    """Re-debounce film tags onto the existing Phase-3 timeline (no full re-track)."""
    try:
        return refresh_team_splits(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase4")
def api_match_pack_phase4(
    pack_id: str,
    max_shots_per_90: float = Query(16.0, ge=6.0, le=40.0),
    min_gap_sec: float = Query(45.0, ge=20.0, le=120.0),
) -> dict[str, Any]:
    """Phase 4: rescore film Shot tags → approximate board shots (SoT via Phase 5)."""
    try:
        return start_phase4(
            pack_id, max_shots_per_90=max_shots_per_90, min_gap_sec=min_gap_sec
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase5")
def api_match_pack_phase5(pack_id: str) -> dict[str, Any]:
    """Phase 5: classify approximate SoT on Phase 4 shots (saves + deflections)."""
    try:
        return start_phase5(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase6")
def api_match_pack_phase6(pack_id: str) -> dict[str, Any]:
    """Phase 6: GK shots faced / saves from opponent SoT + fact goals conceded."""
    try:
        return start_phase6(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase7")
def api_match_pack_phase7(
    pack_id: str,
    max_tackles_per_90: float = Query(18.0, ge=6.0, le=40.0),
    min_gap_sec: float = Query(30.0, ge=15.0, le=90.0),
) -> dict[str, Any]:
    """Phase 7: approximate pass completion + tackle rescore."""
    try:
        return start_phase7(
            pack_id,
            max_tackles_per_90=max_tackles_per_90,
            min_gap_sec=min_gap_sec,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/match-packs/{pack_id}/phase8")
def api_match_pack_phase8(pack_id: str) -> dict[str, Any]:
    """Phase 8: progressive passes, aerials, interceptions, clearances."""
    try:
        return start_phase8(pack_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@lru_cache(maxsize=8)
def _cached_stats(game_id: int) -> dict[str, Any]:
    bundle = load_match(game_id)
    return compute_match_stats(bundle)
