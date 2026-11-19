# StatMan

Football match stats for the StatMan site: expected goals, PPDA, possession, shots, passes, passing accuracy, progressive passes, aerials, tackles, interceptions, and clearances.

## What’s here

- [docs/football-stats-repos.md](docs/football-stats-repos.md) — GitHub repos that collect or compute these stats
- `statman/` — backend that loads StatsBomb open-data matches, converts them to SPADL via [socceraction](https://github.com/ML-KULeuven/socceraction), and returns JSON
- `web/` — match UI, **season view**, and **full-match video upload**

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
- http://127.0.0.1:8000/video — upload a **full match** video (90–120′+)
- http://127.0.0.1:8000/api/docs — interactive API docs
- `GET /api/matches/8657/maps/shots.png` — shot map (xG)
- `GET /api/matches/8657/maps/progressive.png` — progressive passes
- `GET /api/matches/8657/maps/defence.png` — tackles & interceptions
- `POST /api/seasons/43/3/build` — start World Cup 2018 store
- `GET /api/seasons/43/3/table` — aggregated table JSON
- `POST /api/video/jobs` — multipart upload of a full-match file (up to 4&nbsp;GB)
- `GET /api/video/jobs/{id}` — progress + approximate action stats

Per-match payloads are cached in `.data/seasons/c43_s3/matches/`. Re-running build skips matches that are already stored unless you pass `--force` / `force=true`.

## Stat definitions (short)

| Field | Source |
| --- | --- |
| `xg` | Sum of StatsBomb `shot.statsbomb_xg` on raw shots |
| `possession_pct` | Share of StatsBomb possession-chain duration |
| `pass_accuracy` | Successful SPADL passes / attempted |
| `progressive_passes` | Completed passes advancing ≥10 yards toward goal, or into the box (excludes defending 40%) |
| `ppda` | Opponent passes in their own 60% ÷ this team’s tackles + interceptions + fouls in that zone |
| `tackles` / `interceptions` / `clearances` | SPADL action types |
| `aerials_*` | Raw StatsBomb aerial duels (SPADL drops these) |

### Full-match video (approximate)

Upload a complete broadcast (not a highlight clip). The spotter samples the **entire** timeline (default 0.5&nbsp;fps, capped at 150&nbsp;minutes) and tags SoccerNet-style ball actions. It does **not** produce provider-grade xG, PPDA, possession %, progressive passes, pass accuracy, or aerial duels — those stay on the StatsBomb/SPADL path.

Jobs and uploads live under `.data/videos/`.

Data is from [StatsBomb open data](https://github.com/statsbomb/open-data) for the event path. Attribute StatsBomb if you publish analysis based on it, and read their licence before putting numbers on a public product site.
