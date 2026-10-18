"""Phase 8 job wrapper (background thread)."""

from __future__ import annotations

import threading
import time
from typing import Any

from statman.match_pack import store
from statman.match_pack.secondary import run_phase8

_LOCK = threading.Lock()
_ACTIVE_PACK: str | None = None


def start_phase8(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    p8 = meta.get("phase8") or {}
    if p8.get("status") in {"queued", "running"}:
        return meta

    meta["phase8"] = {
        "status": "queued",
        "progress": {"stage": "queued", "pct": 0},
        "error": None,
        "cancel_requested": False,
        "updated_at": time.time(),
    }
    store.write_meta(pack_id, meta)

    def _run() -> None:
        global _ACTIVE_PACK
        with _LOCK:
            while _ACTIVE_PACK is not None:
                time.sleep(0.2)
            _ACTIVE_PACK = pack_id
        try:
            run_phase8(pack_id)
        except Exception as exc:  # noqa: BLE001
            cur = store.read_meta(pack_id) or meta
            cur["phase8"] = {
                "status": "error",
                "error": str(exc),
                "progress": {"stage": "error", "pct": 0},
                "updated_at": time.time(),
            }
            store.write_meta(pack_id, cur)
        finally:
            with _LOCK:
                if _ACTIVE_PACK == pack_id:
                    _ACTIVE_PACK = None

    threading.Thread(target=_run, name=f"statman-phase8-{pack_id}", daemon=True).start()
    return store.read_meta(pack_id) or meta
