"""Apply SQL migrations. Safe to call on every process start."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("statman.persistence")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
# Arbitrary constant. Session lock so two boot processes don't apply at once.
ADVISORY_LOCK_KEY = 58421021

_BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def split_sql(script: str) -> list[str]:
    """Split a migration file into statements.

    Semicolons end a statement only at the end of a line. The shipped
    migrations follow that style so comments and parentheses stay intact.
    """

    statements: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buf).strip()
            if statement.endswith(";"):
                statement = statement[:-1].strip()
            if statement:
                statements.append(statement)
            buf = []
    tail = "\n".join(buf).strip().rstrip(";").strip()
    if tail:
        statements.append(tail)
    return statements


def apply_migrations(conn) -> list[str]:
    """Apply pending migrations. Returns the versions applied this call."""

    conn.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
    try:
        conn.execute(_BOOTSTRAP)
        conn.commit()
        applied = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        new: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name
            if version in applied:
                continue
            for statement in split_sql(path.read_text(encoding="utf-8")):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)",
                (version,),
            )
            conn.commit()
            new.append(version)
            log.info("Applied migration %s", version)
        return new
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
            conn.commit()
        except Exception:  # noqa: BLE001 - unlock is best-effort after a failed migration
            log.warning("Could not release migration advisory lock", exc_info=True)
