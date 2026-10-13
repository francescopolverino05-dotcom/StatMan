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
- http://127.0.0.1:8000/match-pack — **Match pack** Phases 1–6: facts, film tags, kit tracking/possession, rescored shots, SoT, GK saves
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

Jobs and uploads live under `.data/videos/`. YOLO weights cache under `.data/models/`.

### Event-data import (provider path)

For a game you already have as StatsBomb open-data JSON or Opta F24 JSON, use `/import` (or `POST /api/imports`). That path converts to SPADL and returns the same possession / xG / PPDA / progressive-pass stats as the open-data match view. Imports live under `.data/imports/`.

Data is from [StatsBomb open data](https://github.com/statsbomb/open-data) for the event path. Attribute StatsBomb if you publish analysis based on it, and read their licence before putting numbers on a public product site.
