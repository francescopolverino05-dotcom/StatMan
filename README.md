# StatMan — stats viewer + exporter

StatMan does **not** tag matches. It loads finished stats and shows / exports them.

Live: https://statman-production.up.railway.app

## Pages

| Path | What it does |
| --- | --- |
| `/` | **Stats viewer.** Drop a stats package (team CSV + players CSV, optionally shots CSV and the HTML report). Shows team stats and player tables, exports CSV. Saved packages are listed and re-openable (`/?package=<id>`). |
| `/import` | Import StatsBomb-format event JSON (`events` + optional `lineups`/`match`) and view computed team + player stats. CSV export buttons included. |
| `/demo` | StatsBomb open-data World Cup 2018 demo matches (xG, progressive passes, PPDA, maps). CSV export included. |
| `/season`, `/season/team`, `/season/players` | Season aggregates over open-data matches. |

## Stats package format

Upload any of these together (file names are matched case-insensitively; generic names are detected from the header):

* **Team CSV** (`*_team.csv`): `metric,<TeamA>,<TeamB>[,status,reason]`. Rows are grouped into possession, passing, progressive passes, shooting, xG, set pieces/discipline (corners, fouls, cards, offsides) and PPDA (full, 1H, 2H). `;` delimiters are accepted.
* **Players CSV** (`*_players.csv`): header row with at least `team,player`; every other column is shown, sortable and exportable.
* **Shots CSV** (`*_shots.csv`, optional), **HTML report** (`*_stats.html`, optional, shown in a sandboxed iframe), `stats.json` (optional; only `match`/`score` are read).
* `*_team_stats.csv` / `*_player_stats.csv` duplicates are ignored when `*_team.csv` / `*_players.csv` exist.

API: `GET/POST /api/packages`, `GET/DELETE /api/packages/{id}`, `GET /api/packages/{id}/team.csv | players.csv | shots.csv | package.json | report.html`.
Sample package: `tests/fixtures/monopoli_napoli/`.

## Run locally

socceraction needs Python 3.12 or older.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn statman.api:app --reload      # http://localhost:8000
pytest
```

## Storage

Without `DATABASE_URL` everything is JSON under `.data/`. With `DATABASE_URL` (Railway Postgres) packages, imports and season caches are mirrored to Postgres and restored on boot, so they survive redeploys (`GET /api/storage`).

## Deploy

Railway, Dockerfile builder, branch `phase2-autotag`, healthcheck `/api/health`.

## Code map

* `statman/api.py` — FastAPI app, page routes, JSON/CSV endpoints.
* `statman/packages.py` — stats-package parse / store / CSV export.
* `statman/event_import.py`, `statman/compute.py`, `statman/event_metrics.py` — StatsBomb-event → team/player stats (xG, progressive passes, PPDA, ...).
* `statman/maps.py`, `statman/season.py`, `statman/store.py`, `statman/load.py` — open-data demo, maps, season views.
* `statman/persistence/` — file/Postgres document store.
* `web/` — static UI (`index.html` + `viewer.js`, `import.*`, `demo.html` + `app.js`, `season*.html`).

The earlier video tagging / auto-tagger / match-pack code was removed from `HEAD`; it remains in git history.
