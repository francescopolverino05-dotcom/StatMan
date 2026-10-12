# StatMan

Football match stats for the StatMan site: expected goals, PPDA, possession, shots, passes, passing accuracy, progressive passes, aerials, tackles, interceptions, and clearances.

## What’s here

- [docs/football-stats-repos.md](docs/football-stats-repos.md) — GitHub repos that collect or compute these stats
- `statman/` — small backend that loads **one StatsBomb open-data match**, converts it to SPADL via [socceraction](https://github.com/ML-KULeuven/socceraction), and returns JSON

Default demo match: **Belgium 2–0 England**, FIFA World Cup 2018 third place (`game_id=8657`).

## Run the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# One-shot JSON on stdout
python -m statman
python -m statman 8657

# HTTP API + web UI
uvicorn statman.api:app --reload --host 0.0.0.0 --port 8000

# Offline unit tests (no network)
pytest
```

Then open:

- http://127.0.0.1:8000/ — StatMan UI
- http://127.0.0.1:8000/api/docs — interactive API docs
- http://127.0.0.1:8000/api/matches/8657/stats — JSON for the demo match
- http://127.0.0.1:8000/api/games/demo — World Cup 2018 open matches

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

Data is from [StatsBomb open data](https://github.com/statsbomb/open-data). Attribute StatsBomb if you publish analysis based on it, and read their licence before putting numbers on a public product site.
