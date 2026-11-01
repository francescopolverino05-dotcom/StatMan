"""Storage layer tests. Postgres tests run when STATMAN_TEST_DATABASE_URL is set."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from statman import persistence
from statman.persistence import backend as backend_mod
from statman.persistence import mirror
from statman.persistence.migrate import split_sql

PG_URL = os.environ.get("STATMAN_TEST_DATABASE_URL", "").strip()
needs_pg = pytest.mark.skipif(not PG_URL, reason="STATMAN_TEST_DATABASE_URL not set")


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every store at tmp dirs; restore the cached backend afterwards."""
    import statman.event_import as ei
    import statman.packages as pk
    import statman.store as ss

    monkeypatch.setattr(pk, "ROOT", tmp_path / "packages")
    monkeypatch.setattr(ei, "ROOT", tmp_path / "imports")
    monkeypatch.setattr(ss, "ROOT", tmp_path / "seasons")
    mirror.reset_state()
    backend_mod.reset_backend()
    yield tmp_path
    backend_mod.reset_backend()
    mirror.reset_state()


@pytest.fixture
def pg(roots, monkeypatch):
    if not PG_URL:
        pytest.skip("STATMAN_TEST_DATABASE_URL not set")
    import psycopg

    with psycopg.connect(PG_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    monkeypatch.setenv("DATABASE_URL", PG_URL)
    backend_mod.reset_backend()
    return roots


# ---- file mode (DATABASE_URL unset) ----------------------------------------


def test_file_mode_is_default(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert persistence.storage_status()["storage"] == "files"
    status = persistence.bootstrap(background=False)
    assert status["storage"] == "files"
    assert persistence.get_backend().name == "files"
    assert mirror.sync_all() == {name: (0, 0) for name in mirror.collections()}


def test_file_backend_roundtrip_preserves_text(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    b = persistence.get_backend()
    text = '{\n  "b": 1,\n  "a": 2\n}'
    b.put_text("packages", "abc/pack.json", text)
    assert (roots / "packages" / "abc" / "pack.json").read_text() == text
    assert b.get_text("packages", "abc/pack.json") == text
    assert [e.key for e in b.list_entries("packages")] == ["abc/pack.json"]
    b.delete_prefix("packages", "abc/")
    assert b.get_text("packages", "abc/pack.json") is None


def test_keys_cannot_escape_root(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    b = persistence.get_backend()
    for bad in ("../x.json", "/etc/passwd", "a/../../x.json", ""):
        with pytest.raises(ValueError):
            b.put_text("packages", bad, "{}")


def test_package_store_in_file_mode(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from statman import packages

    pkg = packages.create_package(
        [("A-B_team.csv", b"metric,A,B\nShots,3,4\n"), ("A-B_players.csv", b"team,player,shots\nA,x,3\n")]
    )
    assert packages.get_package(pkg["package_id"])["team"]["teams"] == ["A", "B"]
    assert [m["package_id"] for m in packages.list_packages()] == [pkg["package_id"]]


def test_split_sql_handles_migration_file():
    sql = (Path(persistence.__file__).parent / "migrations" / "001_initial.sql").read_text()
    stmts = split_sql(sql)
    assert any(s.startswith("CREATE TABLE IF NOT EXISTS events") for s in stmts)
    assert all(not s.rstrip().endswith(";") for s in stmts)


# ---- Postgres ---------------------------------------------------------------


@needs_pg
def test_migrations_create_phase2_tables_idempotently(pg):
    import psycopg

    from statman.persistence.migrate import apply_migrations

    persistence.get_backend()  # applies migrations
    with psycopg.connect(PG_URL) as conn:
        assert apply_migrations(conn) == []  # second run is a no-op
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        }
        assert {"documents", "matches", "players", "squads", "lineups", "events",
                "corrections", "schema_migrations", "event_review_queue"} <= tables
        cols = {
            r[0]
            for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='events'"
            )
        }
        assert {"match_id", "period", "clock_ms", "video_ts_ms", "team", "player_id", "type",
                "outcome", "x", "y", "end_x", "end_y", "body_part", "headed", "line_broken",
                "flags", "confidence", "review_status", "source", "created_at",
                "updated_at"} <= cols
        conn.execute("INSERT INTO matches (id) VALUES ('m1')")
        conn.execute("INSERT INTO players (id, display_name) VALUES ('p1', 'A')")
        conn.execute("INSERT INTO lineups (match_id, player_id, team_side, role, on_clock_ms) "
                     "VALUES ('m1', 'p1', 'home', 'sub', 3600000)")
        eid = conn.execute(
            "INSERT INTO events (match_id, type, player_id, confidence) "
            "VALUES ('m1', 'pass', 'p1', 0.4) RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO corrections (event_id, match_id, before, after) "
                     "VALUES (%s, 'm1', '{}', '{\"type\":\"shot\"}')", (eid,))
        assert conn.execute("SELECT count(*) FROM event_review_queue").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO events (match_id, type, confidence) VALUES ('m1','x',1.5)")
        conn.rollback()


@needs_pg
def test_pg_backend_roundtrip(pg):
    b = persistence.get_backend()
    assert b.name == "postgres"
    b.put_text("packages", "a/pack.json", '{"x": NaN, "y": [1, 2]}')
    assert json.loads(b.get_text("packages", "a/pack.json")) == {"x": None, "y": [1, 2]}
    b.put_text("packages", "a/raw.json", "not json")
    assert b.get_text("packages", "a/raw.json") == "not json"
    assert sorted(e.key for e in b.list_entries("packages", "a/")) == ["a/pack.json", "a/raw.json"]
    b.delete_prefix("packages", "a/")
    assert b.list_entries("packages") == []


@needs_pg
def test_redeploy_survives_via_restore(pg):
    """Write through the normal stores, wipe the disk, restore from Postgres."""
    from statman import event_import, packages, store as season_store

    persistence.bootstrap(background=False)
    pkg = packages.create_package(
        [("A-B_team.csv", b"metric,A,B\nShots,3,4\n"), ("A-B_stats.html", b"<h1>A 1-0 B</h1>")]
    )
    pid = pkg["package_id"]
    work = event_import.import_dir("i1")
    (work / "stats.json").write_text('{"xg": 1.2}')
    (work / "meta.json").write_text('{"import_id": "i1"}')
    (work / "raw" / "events").mkdir(parents=True)
    (work / "raw" / "events" / "9.json").write_text("[]")
    season_store.save_match(43, 3, 9, {"g": 1})

    persistence.sync_all()
    keys = {e.key for e in persistence.get_backend().list_entries("imports")}
    assert keys == {"i1/stats.json", "i1/meta.json"}

    # "Redeploy": container disk is gone.
    shutil.rmtree(pg)
    mirror.reset_state()
    backend_mod.reset_backend()
    persistence.bootstrap(background=False)

    assert packages.get_package(pid)["title"] == "A 1-0 B"
    assert [m["package_id"] for m in packages.list_packages()] == [pid]
    assert json.loads((event_import.import_dir("i1") / "stats.json").read_text()) == {"xg": 1.2}
    assert season_store.load_match_stats(43, 3, 9) == {"g": 1}


@needs_pg
def test_deleting_a_file_deletes_the_document(pg):
    from statman import packages

    persistence.bootstrap(background=False)
    pkg = packages.create_package([("A-B_team.csv", b"metric,A,B\nShots,3,4\n")])
    persistence.sync_all()
    assert packages.delete_package(pkg["package_id"])
    assert mirror.sync("packages")[1] == 2
    assert persistence.get_backend().list_entries("packages") == []


@needs_pg
def test_api_lifespan_and_write_sync(pg):
    from fastapi.testclient import TestClient

    from statman.api import app

    with TestClient(app) as client:
        assert client.get("/api/storage").json()["storage"] == "postgres"
        r = client.post("/api/packages", files=[("files", ("A-B_team.csv", b"metric,A,B\nShots,3,4\n", "text/csv"))])
        assert r.status_code == 200
        keys = {e.key for e in persistence.get_backend().list_entries("packages")}
        assert f"{r.json()['package_id']}/package.json" in keys
