"""Phase 4 job wrapper (background thread)."""

from __future__ import annotations

import threading
import time
from typing import Any

from statman.match_pack import store
from statman.match_pack.shots import run_phase4

_LOCK = threading.Lock()
_ACTIVE_PACK: str | None = None


def start_phase4(
    pack_id: str,
    *,
    max_shots_per_90: float = 16.0,
    min_gap_sec: float = 45.0,
) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    p4 = meta.get("phase4") or {}
    if p4.get("status") in {"queued", "running"}:
        return meta

    meta["phase4"] = {
        "status": "queued",
        "progress": {"stage": "queued", "pct": 0},
        "config": {
            "max_shots_per_90": max_shots_per_90,
            "min_gap_sec": min_gap_sec,
        },
        "error": None,
        "cancel_requested": False,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)

    def _run() -> None:
        global _ACTIVE_PACK
        with _LOCK:
            while _ACTIVE_PACK is not None:
                time.sleep(1.0)
            _ACTIVE_PACK = pack_id
        try:
            run_phase4(
                pack_id,
                max_shots_per_90=max_shots_per_90,
                min_gap_sec=min_gap_sec,
            )
        finally:
            with _LOCK:
                if _ACTIVE_PACK == pack_id:
                    _ACTIVE_PACK = None

    threading.Thread(target=_run, name=f"statman-phase4-{pack_id}", daemon=True).start()
    return store.read_meta(pack_id) or meta
