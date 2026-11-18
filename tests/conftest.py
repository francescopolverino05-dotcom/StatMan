"""Keep pytest off a real DATABASE_URL.

The file backend is the default. Postgres tests set DATABASE_URL themselves
from STATMAN_TEST_DATABASE_URL and drop that database's public schema.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _file_storage_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("STATMAN_VIDEO_DIR", raising=False)
    yield
