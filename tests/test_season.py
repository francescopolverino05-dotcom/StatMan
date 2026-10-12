"""Offline season aggregation tests (no network)."""

from __future__ import annotations

from pathlib import Path

import statman.store as store
from statman.season import player_leaderboard, team_page, tournament_table


def _fake_match(
    game_id: int,
    *,
    date: str,
    home: tuple[int, str, int, dict],
    away: tuple[int, str, int, dict],
) -> dict:
    home_id, home_name, home_score, home_stats = home
    away_id, away_name, away_score, away_stats = away
    return {
        "match": {
            "game_id": game_id,
            "competition": "FIFA World Cup",
            "season": "2018",
            "game_date": date,
            "home_team_id": home_id,
            "away_team_id": away_id,
            "home_team": home_name,
            "away_team": away_name,
            "home_score": home_score,
            "away_score": away_score,
        },
        "teams": [
            {"team_id": home_id, "team_name": home_name, **home_stats},
            {"team_id": away_id, "team_name": away_name, **away_stats},
        ],
        "players": [
            {
                "player_id": home_id * 10 + 1,
                "player_name": f"{home_name} Striker",
                "team_id": home_id,
                "team_name": home_name,
                "xg": home_stats["xg"] * 0.6,
                "goals": home_score,
                "shots": home_stats["shots"],
                "passes_attempted": 20,
                "passes_completed": 16,
                "progressive_passes": home_stats["progressive_passes"] // 2,
                "tackles": 1,
                "interceptions": 0,
                "clearances": 0,
                "aerials_won": 1,
                "aerials_lost": 0,
            },
            {
                "player_id": away_id * 10 + 1,
                "player_name": f"{away_name} Mid",
                "team_id": away_id,
                "team_name": away_name,
                "xg": away_stats["xg"] * 0.5,
                "goals": away_score,
                "shots": away_stats["shots"],
                "passes_attempted": 30,
                "passes_completed": 27,
                "progressive_passes": away_stats["progressive_passes"] // 2,
                "tackles": 2,
                "interceptions": 3,
                "clearances": 1,
                "aerials_won": 0,
                "aerials_lost": 1,
            },
        ],
    }


def test_tournament_table_and_team_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store, "ROOT", tmp_path)
    comp, season = 43, 3
    store.write_meta(
        comp,
        season,
        {
            "competition_id": comp,
            "season_id": season,
            "competition": "FIFA World Cup",
            "season": "2018",
            "status": "ready",
            "games_total": 2,
            "games_done": 2,
        },
    )
    base = {
        "possession_pct": 50.0,
        "ppda": 10.0,
        "progressive_passes": 40,
        "passes_attempted": 100,
        "passes_completed": 80,
        "shots": 8,
        "tackles": 5,
        "interceptions": 4,
        "clearances": 3,
        "aerials_won": 2,
        "aerials_lost": 1,
        "xg": 1.2,
    }
    store.save_match(
        comp,
        season,
        1,
        _fake_match(
            1,
            date="2018-06-14",
            home=(771, "Russia", 5, {**base, "xg": 1.5, "possession_pct": 40.0}),
            away=(772, "Saudi Arabia", 0, {**base, "xg": 0.3, "possession_pct": 60.0}),
        ),
    )
    store.save_match(
        comp,
        season,
        2,
        _fake_match(
            2,
            date="2018-06-19",
            home=(771, "Russia", 1, {**base, "xg": 0.8, "ppda": 8.0}),
            away=(773, "Egypt", 1, {**base, "xg": 0.9, "ppda": 12.0}),
        ),
    )

    table = tournament_table(comp, season)
    assert table["matches_used"] == 2
    russia = next(t for t in table["teams"] if t["team_id"] == 771)
    assert russia["played"] == 2
    assert russia["wins"] == 1
    assert russia["draws"] == 1
    assert russia["points"] == 4
    assert russia["goals_for"] == 6
    assert russia["xg_for"] == 2.3

    page = team_page(771, comp, season)
    assert page["team_name"] == "Russia"
    assert len(page["matches"]) == 2
    assert page["matches"][0]["opponent"] == "Saudi Arabia"
    assert page["matches"][0]["result"] == "W"

    board = player_leaderboard(comp, season, sort="xg", limit=10)
    assert board["matches_used"] == 2
    assert board["players"][0]["xg"] >= board["players"][-1]["xg"]
