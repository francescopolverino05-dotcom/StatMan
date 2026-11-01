"""Stats package viewer/exporter: parsing, API, no tagging routes."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import statman.packages as packages
from statman.api import app

FIX = Path(__file__).parent / "fixtures" / "monopoli_napoli"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(packages, "ROOT", tmp_path / "packages")
    return TestClient(app)


def _files(*names):
    return [("files", (n, (FIX / n).read_bytes(), "application/octet-stream")) for n in names]


ALL = (
    "Monopoli-Napoli_team.csv",
    "Monopoli-Napoli_players.csv",
    "Monopoli-Napoli_shots.csv",
    "Monopoli-Napoli_stats.html",
)


def test_load_full_package(client):
    r = client.post("/api/packages", files=_files(*ALL))
    assert r.status_code == 200, r.text
    pkg = r.json()
    assert pkg["title"].startswith("Monopoli 0-0 Napoli")
    assert pkg["teams"] == ["Monopoli", "Napoli"]
    assert pkg["has_report"] and pkg["shots"] and pkg["players"]["columns"][:2] == ["team", "player"]
    assert len(pkg["players"]["rows"]) == 32
    assert any("ESTIMATES" in n for n in pkg["notes"])
    assert "report_html" not in pkg


def test_team_sections_cover_requested_stats(client):
    pkg = client.post("/api/packages", files=_files(*ALL)).json()
    by = {r["metric"]: r["section"] for r in pkg["team"]["rows"]}
    assert by["Possession % (share of tagged on-ball events)"] == "possession"
    assert by["Passes"] == "passing" and by["Pass accuracy %"] == "passing"
    assert by["Progressive passes attempted"] == "progressive"
    assert by["Progressive pass %"] == "progressive"
    assert by["Shots"] == "shooting" and by["Shots on target"] == "shooting"
    assert by["xG (ESTIMATED)"] == "xg"
    for k in ("Corners", "Fouls committed", "Yellow cards (official)", "Offsides"):
        assert by[k] == "setpieces"
    assert by["PPDA full match"] == by["PPDA 1st half"] == by["PPDA 2nd half"] == "ppda"


def test_exports_round_trip(client):
    pid = client.post("/api/packages", files=_files(*ALL)).json()["package_id"]
    team = client.get(f"/api/packages/{pid}/team.csv")
    assert team.headers["content-type"].startswith("text/csv")
    assert team.text == (FIX / "Monopoli-Napoli_team.csv").read_text()
    players = client.get(f"/api/packages/{pid}/players.csv")
    assert list(csv.reader(io.StringIO(players.text))) == list(
        csv.reader(io.StringIO((FIX / "Monopoli-Napoli_players.csv").read_text()))
    )
    assert client.get(f"/api/packages/{pid}/shots.csv").status_code == 200
    rep = client.get(f"/api/packages/{pid}/report.html")
    assert "sandbox" in rep.headers["content-security-policy"]
    assert client.get(f"/api/packages/{pid}/package.json").json()["package_id"] == pid


def test_duplicate_stats_csv_names_and_unknown_files(client):
    team = (FIX / "Monopoli-Napoli_team.csv").read_bytes()
    r = client.post(
        "/api/packages",
        files=[
            ("files", ("M_team_stats.csv", team, "text/csv")),
            ("files", ("M_team.csv", team, "text/csv")),
            ("files", ("notes.pdf", b"%PDF", "application/pdf")),
        ],
    )
    pkg = r.json()
    assert pkg["files_used"] == ["M_team.csv"] and pkg["files_ignored"] == ["notes.pdf"]


def test_generic_file_names_detected_by_header(client):
    r = client.post(
        "/api/packages",
        files=[
            ("files", ("a.csv", b"metric;A;B\nShots;3;4\n", "text/csv")),
            ("files", ("b.csv", b"team,player,shots\nA,x,3\n", "text/csv")),
        ],
        data={"title": "My game"},
    )
    pkg = r.json()
    assert pkg["title"] == "My game"
    assert pkg["team"]["rows"][0]["home"] == "3" and pkg["players"]["rows"][0][1] == "x"


def test_bad_uploads(client):
    assert client.post("/api/packages", files=_files("Monopoli-Napoli_stats.html")).status_code == 400
    r = client.post("/api/packages", files=[("files", ("x_team.csv", b"metric,A\n", "text/csv"))])
    assert r.status_code == 400
    assert client.get("/api/packages/nothere00000").status_code == 404
    assert client.get("/api/packages/..%2f..%2fetc").status_code in (404, 400)


def test_list_and_delete(client):
    pid = client.post("/api/packages", files=_files(*ALL)).json()["package_id"]
    assert [p["package_id"] for p in client.get("/api/packages").json()["packages"]] == [pid]
    assert client.delete(f"/api/packages/{pid}").status_code == 200
    assert client.get("/api/packages").json()["count"] == 0


def test_tagging_is_gone(client):
    for path in ("/tag", "/review", "/matchsheet", "/video", "/match", "/match-pack"):
        assert client.get(path).status_code == 404, path
    for path in (
        "/api/semi/x",
        "/api/autotag/tagger",
        "/api/autotag/matches",
        "/api/video/jobs",
        "/api/match-packs",
    ):
        assert client.get(path).status_code == 404, path
    for path in ("/static/tag.js", "/static/tag.html", "/static/review.js", "/static/video.js"):
        assert client.get(path).status_code == 404, path
    routes = {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in routes if any(w in p for w in ("tag", "semi", "autotag", "review", "match-pack", "/video"))]


def test_viewer_pages_served(client):
    for path in ("/", "/viewer", "/import", "/demo", "/season"):
        assert client.get(path).status_code == 200, path
    assert "viewer.js" in client.get("/").text
