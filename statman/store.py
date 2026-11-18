"""Disk store for per-match season stats under ``.data/seasons/``."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent / ".data" / "seasons"


from statman.persistence.mirror import register as _register_collection

_register_collection("seasons", lambda: ROOT)
_LOCK = threading.Lock()


def season_key(competition_id: int, season_id: int) -> str:
    return f"c{competition_id}_s{season_id}"


def season_dir(competition_id: int, season_id: int) -> Path:
    path = ROOT / season_key(competition_id, season_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "matches").mkdir(exist_ok=True)
    return path


def meta_path(competition_id: int, season_id: int) -> Path:
    return season_dir(competition_id, season_id) / "meta.json"


def match_path(competition_id: int, season_id: int, game_id: int) -> Path:
    return season_dir(competition_id, season_id) / "matches" / f"{game_id}.json"


def read_meta(competition_id: int, season_id: int) -> dict[str, Any] | None:
    path = meta_path(competition_id, season_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_meta(competition_id: int, season_id: int, meta: dict[str, Any]) -> None:
    path = meta_path(competition_id, season_id)
    with _LOCK:
        path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")


def save_match(
    competition_id: int,
    season_id: int,
    game_id: int,
    payload: dict[str, Any],
) -> Path:
    path = match_path(competition_id, season_id, game_id)
    with _LOCK:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_match_stats(
    competition_id: int,
    season_id: int,
    game_id: int,
) -> dict[str, Any] | None:
    path = match_path(competition_id, season_id, game_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_stored_game_ids(competition_id: int, season_id: int) -> list[int]:
    matches = season_dir(competition_id, season_id) / "matches"
    ids = []
    for path in matches.glob("*.json"):
        try:
            ids.append(int(path.stem))
        except ValueError:
            continue
    return sorted(ids)


def iter_stored_matches(
    competition_id: int,
    season_id: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for game_id in list_stored_game_ids(competition_id, season_id):
        payload = load_match_stats(competition_id, season_id, game_id)
        if payload is not None:
            out.append(payload)
    out.sort(key=lambda row: str(row.get("match", {}).get("game_date") or ""))
    return out
