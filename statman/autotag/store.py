"""JSON documents for auto-tagging under ``.data/autotag/<match_id>/``.

job.json, clips.json, lineup.json always live here (mirrored to Postgres
documents like every other store). events.json / corrections.json are used
only by the file repository; with DATABASE_URL set, events and corrections are
rows in the ``events`` / ``corrections`` tables (see ``repo.py``).
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from statman.persistence.mirror import register as _register_collection

ROOT = Path(__file__).resolve().parent.parent.parent / ".data" / "autotag"
LOCK = threading.RLock()
_MATCH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_register_collection("autotag", lambda: ROOT)


def check_match_id(match_id: str) -> str:
    if not _MATCH_ID.fullmatch(match_id or ""):
        raise ValueError(f"invalid match id: {match_id!r}")
    return match_id


def ensure_root() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT


def match_dir(match_id: str) -> Path:
    path = ensure_root() / check_match_id(match_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_doc(match_id: str, name: str, default: Any = None) -> Any:
    path = match_dir(match_id) / f"{name}.json"
    with LOCK:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default


def write_doc(match_id: str, name: str, payload: Any) -> None:
    path = match_dir(match_id) / f"{name}.json"
    with LOCK:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(path)


def list_match_ids() -> list[str]:
    root = ensure_root()
    return sorted(p.name for p in root.iterdir() if p.is_dir() and (p / "job.json").exists())
