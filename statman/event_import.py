"""Import StatsBomb or Opta event JSON and compute StatMan SPADL stats.

This is the path for provider-grade match stats from a game you already have
as event data. Video spotting stays approximate and separate.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from statman.compute import compute_match_stats
from statman.load import MatchBundle

ROOT = Path(__file__).resolve().parent.parent / ".data" / "imports"


def ensure_root() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT


def new_import_id() -> str:
    return uuid.uuid4().hex[:12]


def import_dir(import_id: str) -> Path:
    path = ensure_root() / import_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def detect_format(payload: Any, filename: str = "") -> str:
    """Return ``statsbomb``, ``opta_f24``, or raise ValueError."""
    name = filename.lower()
    if "f24" in name or "opta" in name:
        return "opta_f24"
    if isinstance(payload, list) and payload:
        sample = payload[0]
        if isinstance(sample, dict) and ("type" in sample) and (
            "possession" in sample or "period" in sample or "location" in sample
        ):
            return "statsbomb"
    if isinstance(payload, dict):
        # Opta / StatsPerform F24 JSON often wraps Game/Event lists
        if "Game" in payload or "Games" in payload or "eventTypes" in payload:
            return "opta_f24"
        if "events" in payload and isinstance(payload["events"], list):
            return detect_format(payload["events"], filename)
    raise ValueError(
        "Unrecognized event file. Upload StatsBomb events JSON "
        "(open-data events/{match_id}.json) or Opta F24 JSON."
    )


def import_statsbomb(
    events_file: BinaryIO,
    events_filename: str,
    *,
    lineups_file: BinaryIO | None = None,
    lineups_filename: str | None = None,
    match_file: BinaryIO | None = None,
    match_filename: str | None = None,
    game_id: int | None = None,
    home_team_id: int | None = None,
) -> dict[str, Any]:
    """Load StatsBomb open-data-style files and return compute_match_stats output."""
    import_id = new_import_id()
    work = import_dir(import_id)
    events_raw = json.loads(events_file.read().decode("utf-8"))
    if isinstance(events_raw, dict) and "events" in events_raw:
        events_raw = events_raw["events"]
    if not isinstance(events_raw, list) or not events_raw:
        raise ValueError("StatsBomb events file must be a non-empty JSON list")

    fmt = detect_format(events_raw, events_filename)
    if fmt != "statsbomb":
        raise ValueError(f"Expected StatsBomb events, got {fmt}")

    resolved_game_id = game_id or _infer_statsbomb_game_id(events_raw, events_filename)
    lineups_raw = None
    if lineups_file is not None:
        lineups_raw = json.loads(lineups_file.read().decode("utf-8"))
    match_raw = None
    if match_file is not None:
        match_payload = json.loads(match_file.read().decode("utf-8"))
        if isinstance(match_payload, list):
            hits = [m for m in match_payload if int(m.get("match_id", -1)) == resolved_game_id]
            match_raw = hits[0] if hits else match_payload[0]
        elif isinstance(match_payload, dict):
            match_raw = match_payload

    if lineups_raw is None:
        lineups_raw = _lineups_from_events(events_raw)
    if match_raw is None:
        match_raw = _match_from_events(events_raw, resolved_game_id, lineups_raw)

    home_id = home_team_id or int(
        match_raw.get("home_team", {}).get("home_team_id")
        or match_raw.get("home_team_id")
        or lineups_raw[0]["team_id"]
    )

    # Materialize a minimal open-data tree so StatsBombLoader can parse it.
    root = work / "statsbomb"
    comp_id = int(
        match_raw.get("competition", {}).get("competition_id")
        or match_raw.get("competition_id")
        or 0
    )
    season_id = int(
        match_raw.get("season", {}).get("season_id") or match_raw.get("season_id") or 0
    )
    (root / "events").mkdir(parents=True, exist_ok=True)
    (root / "lineups").mkdir(parents=True, exist_ok=True)
    (root / "matches" / str(comp_id)).mkdir(parents=True, exist_ok=True)

    (root / "events" / f"{resolved_game_id}.json").write_text(
        json.dumps(events_raw), encoding="utf-8"
    )
    (root / "lineups" / f"{resolved_game_id}.json").write_text(
        json.dumps(lineups_raw), encoding="utf-8"
    )
    # Flatten match for open-data shape if needed
    match_out = _normalize_match_record(match_raw, resolved_game_id, home_id)
    (root / "matches" / str(comp_id) / f"{season_id}.json").write_text(
        json.dumps([match_out]), encoding="utf-8"
    )
    (root / "competitions.json").write_text(
        json.dumps(
            [
                {
                    "competition_id": comp_id,
                    "season_id": season_id,
                    "country_name": match_raw.get("competition", {}).get("country_name", ""),
                    "competition_name": match_raw.get("competition", {}).get(
                        "competition_name", "Imported"
                    ),
                    "competition_gender": "male",
                    "season_name": match_raw.get("season", {}).get("season_name", "imported"),
                }
            ]
        ),
        encoding="utf-8",
    )

    bundle = _load_statsbomb_local(root, resolved_game_id, home_id, match_out)
    stats = compute_match_stats(bundle)
    stats["source"] = {
        **stats.get("source", {}),
        "import_id": import_id,
        "import_format": "statsbomb",
        "events_filename": Path(events_filename).name,
        "lineups_filename": Path(lineups_filename).name if lineups_filename else None,
        "match_filename": Path(match_filename).name if match_filename else None,
        "quality": "provider",
    }
    _persist_import(import_id, stats, format_name="statsbomb")
    return {"import_id": import_id, "format": "statsbomb", "stats": stats}


def import_opta_f24(
    events_file: BinaryIO,
    events_filename: str,
    *,
    game_id: int | None = None,
    home_team_id: int | None = None,
) -> dict[str, Any]:
    """Import Opta/StatsPerform F24 JSON via socceraction OptaLoader."""
    import_id = new_import_id()
    work = import_dir(import_id)
    raw = events_file.read()
    payload = json.loads(raw.decode("utf-8"))
    fmt = detect_format(payload, events_filename)
    if fmt != "opta_f24":
        raise ValueError(f"Expected Opta F24 JSON, got {fmt}")

    root = work / "opta"
    root.mkdir(parents=True, exist_ok=True)
    # OptaLoader json feeds look for f24 path patterns.
    resolved_game_id = game_id or _infer_opta_game_id(payload) or int(time.time()) % 10_000_000
    dest = root / f"f24-0-0-{resolved_game_id}-eventdetails.json"
    dest.write_bytes(raw)

    from socceraction.data.opta import OptaLoader
    import socceraction.spadl as spadl
    import socceraction.spadl.opta as spadl_opta

    loader = OptaLoader(
        root=str(root),
        parser="json",
        feeds={"f24": "f24-{competition_id}-{season_id}-{game_id}-eventdetails.json"},
    )
    events = loader.events(resolved_game_id)
    if events.empty:
        raise ValueError("Opta F24 file produced no events")

    teams = (
        events[["team_id"]]
        .drop_duplicates()
        .assign(team_name=lambda d: d["team_id"].astype(str))
    )
    # Prefer explicit home_team_id; else first team seen.
    home_id = home_team_id
    if home_id is None:
        home_id = int(events["team_id"].dropna().iloc[0])
    actions = spadl_opta.convert_to_actions(events, home_id)
    actions = (
        actions.merge(spadl.actiontypes_df(), how="left")
        .merge(spadl.results_df(), how="left")
        .merge(spadl.bodyparts_df(), how="left")
    )
    # Minimal player/team name columns for compute_match_stats joins
    if "player_name" not in actions.columns:
        actions["player_name"] = actions.get("player_id")
    if "team_name" not in actions.columns:
        actions = actions.merge(teams, how="left", on="team_id")
    if "nickname" not in actions.columns:
        actions["nickname"] = None

    players = (
        events.dropna(subset=["player_id"])[["player_id", "team_id"]]
        .drop_duplicates("player_id")
        .assign(player_name=lambda d: d["player_id"].astype(str), nickname=None)
    )
    game = {
        "game_id": resolved_game_id,
        "home_team_id": home_id,
        "away_team_id": int(
            next((t for t in events["team_id"].dropna().unique() if int(t) != home_id), home_id)
        ),
        "home_score": None,
        "away_score": None,
        "competition_name": "Imported Opta",
        "season_name": "imported",
        "game_date": None,
    }
    bundle = MatchBundle(
        game_id=resolved_game_id,
        game=game,
        teams=teams,
        players=players,
        events=events,
        actions=actions,
    )
    stats = compute_match_stats(bundle)
    stats["source"] = {
        "provider": "Opta",
        "dataset": "imported-f24",
        "schema": "SPADL via socceraction",
        "import_id": import_id,
        "import_format": "opta_f24",
        "events_filename": Path(events_filename).name,
        "quality": "provider",
    }
    _persist_import(import_id, stats, format_name="opta_f24")
    return {"import_id": import_id, "format": "opta_f24", "stats": stats}


def import_events_auto(
    events_file: BinaryIO,
    events_filename: str,
    *,
    lineups_file: BinaryIO | None = None,
    lineups_filename: str | None = None,
    match_file: BinaryIO | None = None,
    match_filename: str | None = None,
    game_id: int | None = None,
    home_team_id: int | None = None,
) -> dict[str, Any]:
    """Detect format from the events file and import."""
    # Peek without consuming caller's stream permanently — read into memory.
    raw = events_file.read()
    payload = json.loads(raw.decode("utf-8"))
    fmt = detect_format(payload, events_filename)

    from io import BytesIO

    buf = BytesIO(raw)
    if fmt == "statsbomb":
        return import_statsbomb(
            buf,
            events_filename,
            lineups_file=lineups_file,
            lineups_filename=lineups_filename,
            match_file=match_file,
            match_filename=match_filename,
            game_id=game_id,
            home_team_id=home_team_id,
        )
    return import_opta_f24(
        buf,
        events_filename,
        game_id=game_id,
        home_team_id=home_team_id,
    )


def get_import(import_id: str) -> dict[str, Any] | None:
    path = import_dir(import_id) / "stats.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_imports(limit: int = 20) -> list[dict[str, Any]]:
    ensure_root()
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        meta_path = path / "meta.json"
        if not meta_path.exists():
            continue
        rows.append(json.loads(meta_path.read_text(encoding="utf-8")))
        if len(rows) >= limit:
            break
    return rows


def _persist_import(import_id: str, stats: dict[str, Any], *, format_name: str) -> None:
    work = import_dir(import_id)
    (work / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    match = stats.get("match") or {}
    meta = {
        "import_id": import_id,
        "format": format_name,
        "created_at": time.time(),
        "game_id": match.get("game_id"),
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "home_score": match.get("home_score"),
        "away_score": match.get("away_score"),
        "quality": "provider",
    }
    (work / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _infer_statsbomb_game_id(events: list[dict[str, Any]], filename: str) -> int:
    for e in events:
        if e.get("match_id") is not None:
            return int(e["match_id"])
    stem = Path(filename).stem
    if stem.isdigit():
        return int(stem)
    # Stable synthetic id from content length + first event id hash
    return abs(hash(events[0].get("id", "0"))) % 10_000_000


def _infer_opta_game_id(payload: Any) -> int | None:
    if isinstance(payload, dict):
        game = payload.get("Game") or payload.get("game")
        if isinstance(game, dict) and (game.get("@id") or game.get("id")):
            try:
                return int(game.get("@id") or game.get("id"))
            except (TypeError, ValueError):
                pass
        for key in ("game_id", "gameId", "match_id"):
            if key in payload:
                try:
                    return int(payload[key])
                except (TypeError, ValueError):
                    pass
    return None


def _lineups_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    teams: dict[int, dict[str, Any]] = {}
    for e in events:
        team = e.get("team") or {}
        tid = team.get("id")
        if tid is None:
            continue
        tid = int(tid)
        if tid not in teams:
            teams[tid] = {"team_id": tid, "team_name": team.get("name", str(tid)), "lineup": []}
        player = e.get("player")
        if not player:
            continue
        pid = int(player["id"])
        lineup = teams[tid]["lineup"]
        if any(p.get("player_id") == pid for p in lineup):
            continue
        lineup.append(
            {
                "player_id": pid,
                "player_name": player.get("name", str(pid)),
                "player_nickname": None,
                "jersey_number": 0,
                "country": {"id": 0, "name": ""},
            }
        )
    if len(teams) < 2:
        raise ValueError(
            "Could not infer two teams from events. Upload a StatsBomb lineups JSON too."
        )
    return list(teams.values())[:2]


def _match_from_events(
    events: list[dict[str, Any]],
    game_id: int,
    lineups: list[dict[str, Any]],
) -> dict[str, Any]:
    home, away = lineups[0], lineups[1]
    return {
        "match_id": game_id,
        "match_date": "1970-01-01",
        "kick_off": "12:00:00.000",
        "home_score": 0,
        "away_score": 0,
        "home_team": {
            "home_team_id": home["team_id"],
            "home_team_name": home["team_name"],
        },
        "away_team": {
            "away_team_id": away["team_id"],
            "away_team_name": away["team_name"],
        },
        "competition": {
            "competition_id": 0,
            "competition_name": "Imported",
            "country_name": "",
        },
        "season": {"season_id": 0, "season_name": "imported"},
        "competition_stage": {"id": 0, "name": "Imported"},
        "stadium": {"id": 0, "name": None},
        "referee": {"id": 0, "name": None},
        "match_week": 0,
    }


def _normalize_match_record(match_raw: dict[str, Any], game_id: int, home_id: int) -> dict[str, Any]:
    """Ensure open-data match JSON fields exist for StatsBombLoader.games()."""
    out = dict(match_raw)
    out.setdefault("match_id", game_id)
    out.setdefault("match_date", "1970-01-01")
    out.setdefault("kick_off", "12:00:00.000")
    out.setdefault("match_week", 0)
    if "home_team" not in out and "home_team_id" in out:
        out["home_team"] = {
            "home_team_id": out["home_team_id"],
            "home_team_name": out.get("home_team_name", str(out["home_team_id"])),
        }
    if "away_team" not in out and "away_team_id" in out:
        out["away_team"] = {
            "away_team_id": out["away_team_id"],
            "away_team_name": out.get("away_team_name", str(out["away_team_id"])),
        }
    # Prefer caller home_id when present
    if out.get("home_team"):
        out["home_team"]["home_team_id"] = int(
            out["home_team"].get("home_team_id") or home_id
        )
    out.setdefault(
        "competition",
        {"competition_id": out.get("competition_id", 0), "competition_name": "Imported"},
    )
    out.setdefault(
        "season",
        {"season_id": out.get("season_id", 0), "season_name": "imported"},
    )
    out.setdefault("competition_stage", {"id": 0, "name": "Imported"})
    return out


def _load_statsbomb_local(
    root: Path,
    game_id: int,
    home_team_id: int,
    match_out: dict[str, Any],
) -> MatchBundle:
    from socceraction.data.statsbomb import StatsBombLoader
    import socceraction.spadl as spadl

    loader = StatsBombLoader(getter="local", root=str(root))
    teams = loader.teams(game_id)
    players = loader.players(game_id)
    events = loader.events(game_id)
    actions = spadl.statsbomb.convert_to_actions(
        events,
        home_team_id=home_team_id,
        xy_fidelity_version=1,
        shot_fidelity_version=1,
    )
    actions = (
        actions.merge(spadl.actiontypes_df(), how="left")
        .merge(spadl.results_df(), how="left")
        .merge(spadl.bodyparts_df(), how="left")
        .merge(
            players[["player_id", "player_name", "nickname"]].drop_duplicates("player_id"),
            how="left",
            on="player_id",
        )
        .merge(teams[["team_id", "team_name"]].drop_duplicates("team_id"), how="left", on="team_id")
    )
    actions["player_name"] = actions.apply(
        lambda r: r["nickname"] if pd.notna(r.get("nickname")) and r["nickname"] else r["player_name"],
        axis=1,
    )

    home = match_out.get("home_team") or {}
    away = match_out.get("away_team") or {}
    game = {
        "game_id": game_id,
        "home_team_id": int(home.get("home_team_id") or home_team_id),
        "away_team_id": int(away.get("away_team_id") or 0),
        "home_score": match_out.get("home_score"),
        "away_score": match_out.get("away_score"),
        "competition_name": (match_out.get("competition") or {}).get("competition_name"),
        "season_name": (match_out.get("season") or {}).get("season_name"),
        "game_date": match_out.get("match_date"),
        "competition_id": (match_out.get("competition") or {}).get("competition_id"),
        "season_id": (match_out.get("season") or {}).get("season_id"),
    }
    return MatchBundle(
        game_id=game_id,
        game=game,
        teams=teams,
        players=players,
        events=events,
        actions=actions,
    )


def cleanup_import(import_id: str) -> None:
    path = ensure_root() / import_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
