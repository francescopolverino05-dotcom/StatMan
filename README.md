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

Jobs and uploads live under `.data/videos/`. YOLO weights cache under `.data/models/`.

### Event-data import (provider path)

For a game you already have as StatsBomb open-data JSON or Opta F24 JSON, use `/import` (or `POST /api/imports`). That path converts to SPADL and returns the same possession / xG / PPDA / progressive-pass stats as the open-data match view. Imports live under `.data/imports/`.

Data is from [StatsBomb open data](https://github.com/statsbomb/open-data) for the event path. Attribute StatsBomb if you publish analysis based on it, and read their licence before putting numbers on a public product site.

## Persistent storage (Phase 1)

All JSON stores (match packs, event imports, video jobs, season caches) go
through `statman/persistence`:

- `DATABASE_URL` unset: unchanged `.data/` JSON files.
- `DATABASE_URL` set: Postgres. On startup migrations run
  (`statman/persistence/migrations/`), then every stored JSON document is
  restored to `.data/`. New/changed JSON files are synced to Postgres after
  each write request, every `STATMAN_SYNC_INTERVAL_S` seconds (default 5, for
  background pipeline threads) and on shutdown.
- Video binaries never go to Postgres. Set `STATMAN_VIDEO_DIR` to a mounted
  volume (e.g. `/data/videos`) so they survive redeploys.
- Phase 2 tables (`matches`, `squads`, `players`, `lineups`, `events`,
  `corrections`, view `event_review_queue`) are created but not used yet.

Postgres tests: `STATMAN_TEST_DATABASE_URL=postgresql://... pytest tests/test_persistence.py`
(they drop and recreate the `public` schema of that database).

## Phase 2: automatic tagging + review

`statman/autotag/` cuts an uploaded match video into overlapping clips (15 s, 5 s
overlap, ffmpeg) under `STATMAN_VIDEO_DIR/clips/<match_id>/`, tags each clip with a
pluggable `Tagger`, merges duplicates across overlaps, and routes events below
`STATMAN_REVIEW_THRESHOLD` (default 0.75) or with validation issues to the review
queue. Review at `/review?match=<id>`; stats at `/api/autotag/matches/<id>/stats`
(+ `team.csv`, `players.csv`).

| Env var | Purpose |
| --- | --- |
| `TAGGER_API_URL`, `TAGGER_MODEL`, `TAGGER_API_KEY` | OpenAI-compatible vision chat endpoint. Tagger is disabled (job ends `tagger_disabled`, clips kept) when URL or model is unset. |
| `TAGGER_FRAMES` (10), `TAGGER_RESPONSE_FORMAT` (`json_schema`\|`json_object`\|`none`), `TAGGER_TIMEOUT` (120) | Tagger tuning |
| `STATMAN_TAGGER` (`vision_llm`\|`fixture`), `STATMAN_TAGGER_FIXTURE` | Fixture backend for tests/offline demos only |
| `STATMAN_REVIEW_THRESHOLD` | Confidence below which events need review (0.75) |

With `DATABASE_URL` set, events and corrections are rows in the `events` /
`corrections` tables (migration `002_autotag.sql`); otherwise JSON under `.data/autotag/`.

### Score bug reader (autotag)

`statman/autotag/scorebug.py` runs once per auto-tag job before tagging: samples the top-left
score bug every 5 s, OCRs clock + score with `tesseract` (apt `tesseract-ocr`), optional
vision fallback on the crop only (`TAGGER_API_KEY`, `google/gemini-2.5-flash`, disable with
`STATMAN_SCOREBUG_LLM=0`). It sets clip segments/periods (second-half clock reset handled),
inserts confirmed goals (confidence 0.95) and turns AI goals with no score change into
low-confidence `shot` candidates for review. `STATMAN_SCOREBUG=auto|off`;
`STATMAN_SCOREBUG_GOAL_LAG_S` (default 15) = bug update delay after the goal.
No bug / no tesseract -> feature off, job continues unchanged.
