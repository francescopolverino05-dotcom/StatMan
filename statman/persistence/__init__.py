"""Durable storage for StatMan.

One document store backs every JSON store (stats packages, event imports,
season caches):

* ``DATABASE_URL`` set -> Postgres (migrations run automatically on startup)
* unset -> the existing ``.data/`` JSON files, unchanged
"""

from __future__ import annotations

import logging
from typing import Any

from statman.persistence.backend import get_backend, postgres_enabled, reset_backend
from statman.persistence.mirror import (
    register,
    restore_all,
    start_background_sync,
    stop_background_sync,
    sync_all,
)

log = logging.getLogger("statman.persistence")

__all__ = [
    "bootstrap",
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
    return {"storage": "postgres" if postgres_enabled() else "files"}


def _register_stores() -> None:
    # Importing the store modules registers their collections.
    import statman.event_import  # noqa: F401
    import statman.packages  # noqa: F401
    import statman.store  # noqa: F401


def bootstrap(*, background: bool = True) -> dict[str, Any]:
    """Migrate, restore JSON to disk, start background sync. Called on API startup."""
    _register_stores()
    backend = get_backend()  # Postgres: connects and applies migrations
    restored = restore_all() if postgres_enabled() else {}
    if background:
        start_background_sync()
    log.info("StatMan persistence ready backend=%s restored=%s", backend.name, restored)
    return {**storage_status(), "restored": restored}


def shutdown() -> None:
    if postgres_enabled():
        stop_background_sync()
