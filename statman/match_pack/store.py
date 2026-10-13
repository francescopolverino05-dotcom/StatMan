"""Disk store for match packs under ``.data/match_packs/``."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent / ".data" / "match_packs"


def ensure_root() -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT


def new_pack_id() -> str:
    return uuid.uuid4().hex[:12]


def pack_dir(pack_id: str) -> Path:
    path = ensure_root() / pack_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def meta_path(pack_id: str) -> Path:
    return pack_dir(pack_id) / "pack.json"


def write_meta(pack_id: str, meta: dict[str, Any]) -> None:
    path = meta_path(pack_id)
    tmp = path.with_suffix(".tmp")
    meta = {**meta, "updated_at": time.time()}
    tmp.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def read_meta(pack_id: str) -> dict[str, Any] | None:
    path = meta_path(pack_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_meta(limit: int = 20) -> list[dict[str, Any]]:
    ensure_root()
    rows: list[dict[str, Any]] = []
    for path in sorted(ROOT.glob("*/pack.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if len(rows) >= limit:
            break
    return rows
