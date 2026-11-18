# StatMan

Football match stats for the StatMan site: expected goals, PPDA, possession, shots, passes, passing accuracy, progressive passes, aerials, tackles, interceptions, and clearances.

## What’s here

- [docs/football-stats-repos.md](docs/football-stats-repos.md) — GitHub repos that collect or compute these stats
- `statman/` — backend that loads StatsBomb open-data matches, converts them to SPADL via [socceraction](https://github.com/ML-KULeuven/socceraction), and returns JSON
- `web/` — match UI, **season view**, **full-match video upload**, and **event-data import**

Default demo match: **Belgium 2–0 England**, FIFA World Cup 2018 third place (`game_id=8657`).

## Run the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# One-shot JSON on stdout
python -m statman
python -m statman 8657

# Build / inspect a full open competition (World Cup 2018 = 64 matches)
python -m statman season build            # store under .data/seasons/
python -m statman season build --limit 5  # smoke subset
python -m statman season table
python -m statman season players --sort xg

# HTTP API + web UI
uvicorn statman.api:app --reload --host 0.0.0.0 --port 8000

# Offline unit tests (no network)
pytest
```

Then open:

- http://127.0.0.1:8000/ — match UI (tables + pitch maps)
- http://127.0.0.1:8000/season — tournament table (build first)
- http://127.0.0.1:8000/season/players — player leaderboards
- http://127.0.0.1:8000/match-pack — **Match pack** Phases 1–9: full approximate board (facts → film → tracking → shots/SoT/GK → actions → xG/PPDA)
- http://127.0.0.1:8000/video — upload a **full match** video (90–120′+, film tags only)
- http://127.0.0.1:8000/import — import StatsBomb / Opta event JSON (provider-grade path)
- http://127.0.0.1:8000/api/docs — interactive API docs
- `GET /api/matches/8657/maps/shots.png` — shot map (xG)
- `GET /api/matches/8657/maps/progressive.png` — progressive passes
- `GET /api/matches/8657/maps/defence.png` — tackles & interceptions
- `POST /api/seasons/43/3/build` — start World Cup 2018 store
- `GET /api/seasons/43/3/table` — aggregated table JSON
- `POST /api/video/jobs` — multipart upload of a full-match file (up to 4&nbsp;GB)
- `GET /api/video/jobs/{id}` — progress + ETA + approximate action stats
- `POST /api/video/jobs/{id}/cancel` — cancel a queued/running job
- `POST /api/imports` — multipart StatsBomb events (+ optional lineups/match) or Opta F24 JSON
- `GET /api/imports/{id}` — stored import stats

Per-match payloads are cached in `.data/seasons/c43_s3/matches/`. Re-running build skips matches that are already stored unless you pass `--force` / `force=true`.

## Stat catalog (event path)

Team boards on `/` and `/import` collect the full match sheet from StatsBomb events (+ SPADL for PPDA):

| Group | Fields |
| --- | --- |
| Match | Goals, possession %, fouls committed/won, yellow/red cards, offsides & corners (1H/2H/total), free kicks, goal kicks, throw-ins |
| Attack | xG, shots, SoT, shot accuracy %, blocked/missed, inside/outside box, headed shots, key passes, into final third & into box (completed/attempted) |
| Passes | Open-play passes completed/attempted & accuracy, progressive (c/a), crosses, long balls, through balls |
| Defence | Tackles, interceptions, recoveries, high recoveries, balls lost, blocks, clearances, ground/aerial duels (won/total), PPDA |
| Goalkeeper | Shots faced, shots on target faced, goals conceded, saves, save %, passes / accurate |

Definitions ship on every `/api/matches/{id}/stats` response (`catalog_version`, currently `statsbomb-sheet-v1`). Through-balls stay `0` when the feed omits `through_ball` (common on open data). Belgium–England (`8657`) is pinned as a regression fixture under `tests/fixtures/`.

**Import:** StatsBomb JSON is the recommended provider path. Opta F24 is accepted but only partially fills the catalog.

### Full-match video (approximate)

Upload a complete broadcast (not a highlight clip). The spotter samples the **entire** timeline (default 0.5&nbsp;fps, capped at 150&nbsp;minutes), detects people/ball with **YOLO** (`yolov8n`, OpenCV HOG fallback), and tags SoccerNet-style ball actions. Progress includes an ETA; jobs can be cancelled. Treat counts as approximate — not Opta/StatsBomb.

Job JSON lives with the other document stores (`.data/videos/jobs/` on disk, Postgres when `DATABASE_URL` is set). Video bytes stay on disk under `.data/videos/uploads/` unless `STATMAN_VIDEO_DIR` points at a volume. YOLO weights cache under `.data/models/`.

### Event-data import (provider path)

For a game you already have as StatsBomb open-data JSON or Opta F24 JSON, use `/import` (or `POST /api/imports`). That path converts to SPADL and returns the same possession / xG / PPDA / progressive-pass stats as the open-data match view. The saved stats and meta live in the document store (`.data/imports/` locally, Postgres when `DATABASE_URL` is set).

Data is from [StatsBomb open data](https://github.com/statsbomb/open-data) for the event path. Attribute StatsBomb if you publish analysis based on it, and read their licence before putting numbers on a public product site.

## Persistent storage (Phase 1)

Match packs, event imports, video-job JSON, and season caches all go through `statman/persistence`:

- `DATABASE_URL` unset: the same `.data/` JSON files as before (local dev and pytest).
- `DATABASE_URL` set: Postgres. On startup the process applies `statman/persistence/migrations/`, then writes every stored document back under `.data/` so the existing readers keep working. Changed JSON is copied to Postgres after each write request, every `STATMAN_SYNC_INTERVAL_S` seconds (default 5, so background film threads are covered), and again on shutdown.
- Video binaries are never rows. Set `STATMAN_VIDEO_DIR` to a directory on a mounted volume. Job uploads go to `$STATMAN_VIDEO_DIR/uploads/` and match-pack videos to `$STATMAN_VIDEO_DIR/match_packs/<pack_id>/`.
- Phase 2 tables are created now and unused: `matches`, `squads`, `players`, `lineups`, `events` (one row per tagged action, including `match_clock_ms`, `video_ts_ms`, confidence, review status, source), `corrections`, and the `event_review_queue` view.

`GET /api/health` reports `"storage": "postgres"` or `"files"`, and `"video_dir"` (null when the volume path is not set).

### Railway

The `statman` service in project StatMan redeploys onto an empty disk. Do this once:

1. In the StatMan project, **New → Database → PostgreSQL**. Leave the service name as `Postgres` unless you rename it.
2. Open the **statman** service → **Variables** → **New variable** → **Add reference**. Set `DATABASE_URL` to `${{Postgres.DATABASE_URL}}`. Use that reference (the private URL). Do not paste the public proxy URL.
3. Deploy **statman**. The container runs migrations before it serves. Check `GET /api/health` for `"storage": "postgres"`.
4. Optional, for video files: **statman** → **Volumes** → add a volume mounted at `/data`. Add variable `STATMAN_VIDEO_DIR=/data/videos`. Redeploy. Without this volume, JSON still survives and the video bytes do not (`"video_dir": null`).

Leave `DATABASE_URL` unset on a laptop. Pytest uses the file backend. Postgres tests need a disposable database and drop its `public` schema:

```bash
STATMAN_TEST_DATABASE_URL=postgresql:///statman_test pytest tests/test_persistence.py
```
