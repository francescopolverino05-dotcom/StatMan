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
    import statman.match_pack.store as mp
    import statman.store as ss
    import statman.video.store as vs

    monkeypatch.setattr(mp, "ROOT", tmp_path / "match_packs")
    monkeypatch.setattr(ei, "ROOT", tmp_path / "imports")
    monkeypatch.setattr(ss, "ROOT", tmp_path / "seasons")
    monkeypatch.setattr(vs, "ROOT", tmp_path / "videos")
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
    b.put_text("match_packs", "abc/pack.json", text)
    assert (roots / "match_packs" / "abc" / "pack.json").read_text() == text
    assert b.get_text("match_packs", "abc/pack.json") == text
    assert [e.key for e in b.list_entries("match_packs")] == ["abc/pack.json"]
    b.delete_prefix("match_packs", "abc/")
    assert b.get_text("match_packs", "abc/pack.json") is None


def test_keys_cannot_escape_root(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    b = persistence.get_backend()
    for bad in ("../x.json", "/etc/passwd", "a/../../x.json", ""):
        with pytest.raises(ValueError):
            b.put_text("match_packs", bad, "{}")


def test_match_pack_store_unchanged_in_file_mode(roots, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from statman.match_pack import store

    store.write_meta("p1", {"pack_id": "p1", "x": 1})
    assert store.read_meta("p1")["x"] == 1
    assert [m["pack_id"] for m in store.list_meta()] == ["p1"]


def test_video_dir_env(roots, tmp_path, monkeypatch):
    from statman.video import store as vs

    monkeypatch.delenv("STATMAN_VIDEO_DIR", raising=False)
    assert vs.upload_path("j1", "a b.mp4") == roots / "videos" / "uploads" / "j1_a_b.mp4"
    monkeypatch.setenv("STATMAN_VIDEO_DIR", str(tmp_path / "vol"))
    assert vs.upload_path("j1", "a.mp4") == tmp_path / "vol" / "uploads" / "j1_a.mp4"
    from statman.match_pack.pipeline import _pack_video_path

    assert _pack_video_path("p9", "m.mp4") == tmp_path / "vol" / "match_packs" / "p9" / "video_m.mp4"


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
    b.put_text("match_packs", "a/pack.json", '{"x": NaN, "y": [1, 2]}')
    assert json.loads(b.get_text("match_packs", "a/pack.json")) == {"x": None, "y": [1, 2]}
    b.put_text("match_packs", "a/raw.json", "not json")
    assert b.get_text("match_packs", "a/raw.json") == "not json"
    assert sorted(e.key for e in b.list_entries("match_packs", "a/")) == ["a/pack.json", "a/raw.json"]
    b.delete_prefix("match_packs", "a/")
    assert b.list_entries("match_packs") == []


@needs_pg
def test_redeploy_survives_via_restore(pg):
    """Write through the normal stores, wipe the disk, restore from Postgres."""
    from statman import event_import, store as season_store
    from statman.match_pack import store
    from statman.video import store as vs

    persistence.bootstrap(background=False)
    store.write_meta("p1", {"pack_id": "p1", "facts": {"home": "A"}})
    (store.pack_dir("p1") / "film_events.json").write_text('[{"t": 1}]')
    (store.pack_dir("p1") / "video_m.mp4").write_bytes(b"\x00binary")
    vs.write_job("j1", {"id": "j1", "status": "done"})
    vs.upload_path("j1", "m.mp4").write_bytes(b"\x00")
    work = event_import.import_dir("i1")
    (work / "stats.json").write_text('{"xg": 1.2}')
    (work / "meta.json").write_text('{"import_id": "i1"}')
    (work / "raw" / "events").mkdir(parents=True)
    (work / "raw" / "events" / "9.json").write_text("[]")
    season_store.save_match(43, 3, 9, {"g": 1})

    persistence.sync_all()
    keys = {e.key for e in persistence.get_backend().list_entries("imports")}
    assert keys == {"i1/stats.json", "i1/meta.json"}
    assert {e.key for e in persistence.get_backend().list_entries("videos")} == {"jobs/j1/job.json"}
    assert "p1/video_m.mp4" not in {e.key for e in persistence.get_backend().list_entries("match_packs")}

    # "Redeploy": container disk is gone.
    shutil.rmtree(pg)
    mirror.reset_state()
    backend_mod.reset_backend()
    persistence.bootstrap(background=False)

    assert store.read_meta("p1")["facts"] == {"home": "A"}
    assert [m["pack_id"] for m in store.list_meta()] == ["p1"]
    assert json.loads((store.pack_dir("p1") / "film_events.json").read_text()) == [{"t": 1}]
    assert vs.read_job("j1")["status"] == "done"
    assert json.loads((event_import.import_dir("i1") / "stats.json").read_text()) == {"xg": 1.2}
    assert season_store.load_match_stats(43, 3, 9) == {"g": 1}


@needs_pg
def test_deleting_a_file_deletes_the_document(pg):
    from statman.match_pack import store

    persistence.bootstrap(background=False)
    store.write_meta("p2", {"pack_id": "p2"})
    persistence.sync_all()
    shutil.rmtree(store.pack_dir("p2"))
    assert mirror.sync("match_packs") == (0, 1)
    assert persistence.get_backend().list_entries("match_packs") == []


@needs_pg
def test_api_lifespan_and_write_sync(pg):
    from fastapi.testclient import TestClient

    from statman.api import app
    from statman.match_pack import store

    with TestClient(app) as client:
        assert client.get("/api/storage").json()["storage"] == "postgres"
        store.write_meta("p3", {"pack_id": "p3"})
        client.post("/api/does-not-exist")  # any write request triggers a sync
        keys = {e.key for e in persistence.get_backend().list_entries("match_packs")}
        assert "p3/pack.json" in keys
