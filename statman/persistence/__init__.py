"""Durable storage for StatMan.

One document store backs every JSON store (match packs, event imports, video
jobs, season caches):

* ``DATABASE_URL`` set -> Postgres (migrations run automatically on startup)
* unset -> the existing ``.data/`` JSON files, unchanged

Video binaries are not rows: ``STATMAN_VIDEO_DIR`` (a volume mount) holds them.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from statman.persistence.backend import get_backend, postgres_enabled, reset_backend
from statman.persistence.mirror import (
    register,
    restore_all,
    start_background_sync,
    stop_background_sync,
    sync_all,
)
from statman.persistence.paths import configured_video_dir

log = logging.getLogger("statman.persistence")

__all__ = [
    "bootstrap",
    "configured_video_dir",
    "get_backend",
    "postgres_enabled",
    "register",
    "reset_backend",
    "restore_all",
    "shutdown",
    "storage_status",
    "sync_all",
]


def storage_status() -> dict[str, Any]:
    return {
        "storage": "postgres" if postgres_enabled() else "files",
        "video_dir": os.environ.get("STATMAN_VIDEO_DIR", "").strip() or None,
    }


def _register_stores() -> None:
    # Importing the store modules registers their collections.
    import statman.event_import  # noqa: F401
    import statman.match_pack.store  # noqa: F401
    import statman.store  # noqa: F401
    import statman.video.store  # noqa: F401


def bootstrap(*, background: bool = True) -> dict[str, Any]:
    """Migrate, restore JSON to disk, start background sync. Called on API startup."""
    _register_stores()
    backend = get_backend()  # Postgres: connects and applies migrations
    restored = restore_all() if postgres_enabled() else {}
    if background:
        start_background_sync()
    log.info("StatMan persistence ready backend=%s restored=%s video_dir=%s",
             backend.name, restored, configured_video_dir() or "(default .data)")
    return {**storage_status(), "restored": restored}


def shutdown() -> None:
    if postgres_enabled():
        stop_background_sync()
