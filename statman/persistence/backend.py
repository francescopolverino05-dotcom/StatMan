"""Document storage: local JSON files, or Postgres when DATABASE_URL is set."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, Protocol

log = logging.getLogger("statman.persistence")

_COLLECTION = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_UNSET = object()
_LOCK = threading.Lock()
_ROOTS: dict[str, Callable[[], Path]] = {}
_CACHE: dict[str, Any] = {"backend": None, "url": _UNSET}

# Wrapper for text that is not valid JSON (for example a rejected facts upload).
_RAW_FLAG = "__statman_blob__"


class DocumentStore(Protocol):
    name: str

    def get_text(self, collection: str, key: str) -> str | None: ...

    def put_text(self, collection: str, key: str, text: str) -> None: ...

    def delete(self, collection: str, key: str) -> None: ...

    def delete_prefix(self, collection: str, prefix: str) -> None: ...

    def list_entries(self, collection: str, prefix: str = "") -> list[DocumentEntry]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DocumentEntry:
    key: str
    updated_at: float


def register_collection(name: str, root: Callable[[], Path]) -> None:
    """Register the on-disk root for a collection.

    The callable is invoked on each file-backend operation so tests can
    monkeypatch the module-level ROOT the callable closes over.
    """

    _check_collection(name)
    _ROOTS[name] = root


def postgres_enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


def get_backend() -> DocumentStore:
    """Return the process-wide store. Migrates Postgres on first use."""

    url = os.environ.get("DATABASE_URL", "").strip()
    with _LOCK:
        current = _CACHE["backend"]
        if current is not None and _CACHE["url"] == url:
            return current
        if current is not None:
            current.close()
            _CACHE["backend"] = None
        if url:
            backend: DocumentStore = PostgresBackend(url)
            log.info("StatMan storage backend: postgres")
        else:
            backend = FileBackend()
            log.info("StatMan storage backend: files")
        _CACHE["backend"] = backend
        _CACHE["url"] = url
        return backend


def reset_backend() -> None:
    """Drop the cached backend. Tests call this after changing DATABASE_URL."""

    with _LOCK:
        current = _CACHE["backend"]
        if current is not None:
            current.close()
        _CACHE["backend"] = None
        _CACHE["url"] = _UNSET


def _check_collection(name: str) -> str:
    if not _COLLECTION.fullmatch(name or ""):
        raise ValueError(f"invalid collection: {name!r}")
    return name


def _check_key(key: str) -> str:
    if not isinstance(key, str) or not key or key.startswith("/") or len(key) > 1024:
        raise ValueError(f"invalid document key: {key!r}")
    parts = Path(key).parts
    if ".." in parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid document key: {key!r}")
    return key.replace("\\", "/")


def _like_prefix(prefix: str) -> str:
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return escaped + "%"


def _loads_lenient(text: str) -> Any:
    """Parse JSON, mapping NaN/Infinity to null so Postgres JSONB accepts it."""

    def _constant(_name: str) -> None:
        return None

    value = json.loads(text, parse_constant=_constant)
    return _strip_nonfinite(value)


def _strip_nonfinite(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(k): _strip_nonfinite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nonfinite(v) for v in value]
    return value


def _decode_body(body: Any) -> str:
    if isinstance(body, dict) and body.get(_RAW_FLAG) is True and "text" in body:
        return str(body["text"])
    return json.dumps(body, ensure_ascii=False)


class FileBackend:
    """The current .data JSON layout. Exact file text is preserved."""

    name = "files"

    def get_text(self, collection: str, key: str) -> str | None:
        path = self._path(collection, key)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def put_text(self, collection: str, key: str, text: str) -> None:
        path = self._path(collection, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def delete(self, collection: str, key: str) -> None:
        path = self._path(collection, key)
        if path.is_file():
            path.unlink()

    def delete_prefix(self, collection: str, prefix: str) -> None:
        prefix = prefix.replace("\\", "/")
        for entry in self.list_entries(collection, prefix=prefix):
            self.delete(collection, entry.key)

    def list_entries(self, collection: str, prefix: str = "") -> list[DocumentEntry]:
        root = self._root(collection)
        if not root.exists():
            return []
        prefix = prefix.replace("\\", "/")
        base = root / prefix if prefix else root
        if not base.exists():
            return []
        entries: list[DocumentEntry] = []
        paths = [base] if base.is_file() else base.rglob("*.json")
        for path in paths:
            if not path.is_file() or path.suffix != ".json":
                continue
            rel = path.resolve().relative_to(root.resolve()).as_posix()
            if prefix and not (rel == prefix.rstrip("/") or rel.startswith(prefix)):
                continue
            try:
                updated = path.stat().st_mtime
            except OSError:
                continue
            entries.append(DocumentEntry(rel, updated))
        return entries

    def close(self) -> None:
        return None

    def _root(self, collection: str) -> Path:
        _check_collection(collection)
        try:
            resolver = _ROOTS[collection]
        except KeyError as exc:
            raise KeyError(f"unknown collection: {collection}") from exc
        return Path(resolver())

    def _path(self, collection: str, key: str) -> Path:
        key = _check_key(key)
        root = self._root(collection).resolve()
        path = (root / key).resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"document key escapes collection root: {key}")
        return path


class PostgresBackend:
    """JSONB documents in the `documents` table. Migrations run on connect."""

    name = "postgres"

    def __init__(self, url: str) -> None:
        self._url = url
        self._lock = threading.Lock()
        self._connection: Any = None
        self._migrate()

    def get_text(self, collection: str, key: str) -> str | None:
        _check_collection(collection)
        key = _check_key(key)

        def op(conn: Any) -> str | None:
            row = conn.execute(
                "SELECT body FROM documents WHERE collection = %s AND doc_key = %s",
                (collection, key),
            ).fetchone()
            if row is None:
                return None
            return _decode_body(row[0])

        return self._run(op)

    def put_text(self, collection: str, key: str, text: str) -> None:
        _check_collection(collection)
        key = _check_key(key)
        try:
            body: Any = _loads_lenient(text)
        except json.JSONDecodeError:
            body = {_RAW_FLAG: True, "text": text}

        def op(conn: Any) -> None:
            from psycopg.types.json import Jsonb

            conn.execute(
                """
                INSERT INTO documents (collection, doc_key, body)
                VALUES (%s, %s, %s)
                ON CONFLICT (collection, doc_key)
                DO UPDATE SET body = EXCLUDED.body, updated_at = clock_timestamp()
                """,
                (collection, key, Jsonb(body)),
            )

        self._run(op)

    def delete(self, collection: str, key: str) -> None:
        _check_collection(collection)
        key = _check_key(key)

        def op(conn: Any) -> None:
            conn.execute(
                "DELETE FROM documents WHERE collection = %s AND doc_key = %s",
                (collection, key),
            )

        self._run(op)

    def delete_prefix(self, collection: str, prefix: str) -> None:
        _check_collection(collection)
        prefix = prefix.replace("\\", "/")

        def op(conn: Any) -> None:
            if prefix == "":
                conn.execute("DELETE FROM documents WHERE collection = %s", (collection,))
                return
            conn.execute(
                """
                DELETE FROM documents
                WHERE collection = %s
                  AND (doc_key = %s OR doc_key LIKE %s ESCAPE '\\')
                """,
                (collection, prefix.rstrip("/"), _like_prefix(prefix)),
            )

        self._run(op)

    def list_entries(self, collection: str, prefix: str = "") -> list[DocumentEntry]:
        _check_collection(collection)
        prefix = prefix.replace("\\", "/")

        def op(conn: Any) -> list[DocumentEntry]:
            if prefix:
                rows = conn.execute(
                    """
                    SELECT doc_key, EXTRACT(EPOCH FROM updated_at)
                    FROM documents
                    WHERE collection = %s
                      AND (doc_key = %s OR doc_key LIKE %s ESCAPE '\\')
                    """,
                    (collection, prefix.rstrip("/"), _like_prefix(prefix)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT doc_key, EXTRACT(EPOCH FROM updated_at)
                    FROM documents
                    WHERE collection = %s
                    """,
                    (collection,),
                ).fetchall()
            return [DocumentEntry(str(key), float(updated)) for key, updated in rows]

        return self._run(op)

    def close(self) -> None:
        with self._lock:
            conn = self._connection
            self._connection = None
            if conn is not None and not conn.closed:
                conn.close()

    def _migrate(self) -> None:
        import psycopg

        from statman.persistence.migrate import apply_migrations

        conn = psycopg.connect(self._url, autocommit=False, prepare_threshold=None, application_name="statman")
        try:
            applied = apply_migrations(conn)
        except Exception:
            conn.close()
            raise
        self._connection = conn
        if applied:
            log.info("Postgres migrations applied: %s", ", ".join(applied))

    def _connect(self) -> Any:
        import psycopg

        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(
                self._url,
                autocommit=False,
                prepare_threshold=None,
                application_name="statman",
            )
        return self._connection

    def _run(self, op: Callable[[Any], Any]) -> Any:
        import psycopg

        with self._lock:
            try:
                conn = self._connect()
                result = op(conn)
                conn.commit()
                return result
            except psycopg.OperationalError:
                self._drop_conn()
                conn = self._connect()
                result = op(conn)
                conn.commit()
                return result
            except Exception:
                if self._connection is not None and not self._connection.closed:
                    self._connection.rollback()
                raise

    def _drop_conn(self) -> None:
        conn = self._connection
        self._connection = None
        if conn is not None and not conn.closed:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
