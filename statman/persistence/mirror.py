"""Keep the ``.data`` JSON tree durable in the document store.

Store modules keep reading/writing their JSON files exactly as before (so no
calculation code changes). Each store registers its root as a *collection*.
When Postgres is enabled:

* ``restore_all()`` (startup) writes every stored document back to disk, so a
  fresh container sees all match packs, imports, video jobs and seasons.
* ``sync_all()`` uploads new/changed ``*.json`` files and deletes documents
  whose files were removed. It runs after every API request, on a background
  timer (for pipeline threads), and on shutdown.

With ``DATABASE_URL`` unset everything here is a no-op: files are the store.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

from statman.persistence.backend import get_backend, postgres_enabled, register_collection

log = logging.getLogger("statman.persistence")

Include = Callable[[str], bool]

_COLLECTIONS: dict[str, tuple[Callable[[], Path], Include | None]] = {}
# collection -> {key: (mtime_ns, size)} of what the store is known to hold.
_SEEN: dict[str, dict[str, tuple[int, int]]] = {}
_SYNC_LOCK = threading.RLock()
_TIMER: dict[str, threading.Thread | threading.Event | None] = {"thread": None, "stop": None}


def register(name: str, root: Callable[[], Path], include: Include | None = None) -> None:
    """Register a JSON tree. ``include(rel_key)`` filters which files persist."""
    register_collection(name, root)
    _COLLECTIONS[name] = (root, include)


def collections() -> list[str]:
    return sorted(_COLLECTIONS)


def _scan(name: str) -> dict[str, tuple[int, int]]:
    root_fn, include = _COLLECTIONS[name]
    root = Path(root_fn())
    out: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return out
    for path in root.rglob("*.json"):
        try:
            if not path.is_file():
                continue
            st = path.stat()
        except OSError:
            continue
        key = path.relative_to(root).as_posix()
        if include is not None and not include(key):
            continue
        out[key] = (st.st_mtime_ns, st.st_size)
    return out


def restore(name: str) -> int:
    """Write stored documents to disk where the file is missing. Returns count."""
    if not postgres_enabled():
        return 0
    backend = get_backend()
    root = Path(_COLLECTIONS[name][0]())
    written = 0
    with _SYNC_LOCK:
        for entry in backend.list_entries(name):
            path = root / entry.key
            if path.exists():
                continue
            text = backend.get_text(name, entry.key)
            if text is None:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            try:
                os.utime(path, (entry.updated_at, entry.updated_at))
            except OSError:
                pass
            written += 1
        stored = {e.key for e in backend.list_entries(name)}
        _SEEN[name] = {k: v for k, v in _scan(name).items() if k in stored}
    return written


def sync(name: str) -> tuple[int, int]:
    """Upload changed files and drop deleted ones. Returns (upserted, deleted)."""
    if not postgres_enabled():
        return (0, 0)
    backend = get_backend()
    root = Path(_COLLECTIONS[name][0]())
    up = gone = 0
    with _SYNC_LOCK:
        seen = _SEEN.setdefault(name, {})
        current = _scan(name)
        for key, sig in current.items():
            if seen.get(key) == sig:
                continue
            try:
                text = (root / key).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            backend.put_text(name, key, text)
            seen[key] = sig
            up += 1
        for key in [k for k in seen if k not in current]:
            backend.delete(name, key)
            del seen[key]
            gone += 1
    return up, gone


def restore_all() -> dict[str, int]:
    return {name: restore(name) for name in collections()}


def sync_all() -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for name in collections():
        try:
            result[name] = sync(name)
        except Exception:  # noqa: BLE001 - never break a request on sync failure
            log.exception("persistence sync failed for %s", name)
    return result


def start_background_sync(interval_s: float | None = None) -> None:
    """Periodic sync so writes from background pipeline threads persist."""
    if not postgres_enabled() or _TIMER["thread"] is not None:
        return
    interval = interval_s or float(os.environ.get("STATMAN_SYNC_INTERVAL_S", "5"))
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            sync_all()

    t = threading.Thread(target=loop, name="statman-persistence-sync", daemon=True)
    _TIMER.update(thread=t, stop=stop)
    t.start()


def stop_background_sync() -> None:
    stop = _TIMER.get("stop")
    if isinstance(stop, threading.Event):
        stop.set()
    _TIMER.update(thread=None, stop=None)
    sync_all()


def reset_state() -> None:
    """Tests: forget what has been synced."""
    _SEEN.clear()
