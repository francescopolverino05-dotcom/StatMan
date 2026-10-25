"""Step 5: match sheet facts override tags. Fully offline: the vision model is a fake client, no HTTP."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from statman.autotag import matchsheet as ms
from statman.autotag import store
from statman.autotag.repo import FileEventRepo

FIXTURE_IMG = Path(__file__).parent / "fixtures" / "matchsheet_napoli_spezia_2026-10-24.jpg"
MID = "napolispezia20261024"


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    for k in ("DATABASE_URL", "TAGGER_API_KEY", "MATCHSHEET_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TAGGER_API_URL", "https://openrouter.invalid/api/v1")
    monkeypatch.setattr(store, "ROOT", tmp_path / "autotag")

    import httpx

    class NoNetwork:  # any real HTTP client use fails the test
        def __init__(self, *a, **k):
            raise AssertionError("network access attempted in an offline test")

    monkeypatch.setattr(httpx, "Client", NoNetwork)


def _names(prefix_list):
    return [{"number": n, "name": name, "position": pos, "starter": n <= 11} for n, name, pos in prefix_list]


NAPOLI = _names([
    (1, "Spinelli", "GK"), (2, "Zappalà", "D"), (3, "Santella", "D"), (4, "De Stefano", "D"), (5, "Branchizio", "D"),
    (6, "Lieto", "M"), (7, "Milenyk", "M"), (8, "Chiummariello", "M"), (9, "Pereyra", "M"), (10, "Riccio", "F"),
    (11, "Mané", "F"), (12, "Mirone", "GK"), (13, "Marotta", None), (14, "Natale", None), (15, "Liccardo", None),
    (16, "Anic", None), (17, "De Michele", None), (18, "D'Angelo", None), (19, "Saviano", None), (20, "Baridò", None),
    (21, "Rovetini", None), (22, "Esposito", None), (23, "Ravicchio", None),
])
SPEZIA = _names([
    (1, "Azzioni", "GK"), (2, "Mazzanti", "D"), (3, "Del Sante", "D"), (4, "Longhi", "D"), (5, "Vignali", "D"),
    (6, "Francini", "M"), (7, "D'Ambrosio", "M"), (8, "Vannucci", "M"), (9, "Trentinella", "M"), (10, "Carbone", "F"),
    (11, "Maggiore", "F"), (12, "Guidi", "GK"), (13, "Michelotti", None), (14, "Corallo", None), (15, "Berti", None),
    (16, "D'Auria", None), (17, "Ghetti", None), (18, "Sartori", None), (19, "Ceccarelli", None), (20, "Camara", None),
])

# What the (mocked) vision model returns for the official Napoli 3-1 Spezia sheet, 24/10/2026.
MODEL_FACTS = {
    "home_team": "Napoli", "away_team": "Spezia",
    "lineups": {"home": NAPOLI, "away": SPEZIA},
    "subs": [
        {"minute": 46, "team": "home", "off": 3, "on": 15},
        {"minute": 59, "team": "home", "off": 5, "on": 22},
        {"minute": 59, "team": "home", "off": 9, "on": 20},
        {"minute": 64, "team": "home", "off": 11, "on": 21},
        {"minute": 58, "team": "away", "off": 11, "on": 17},
        {"minute": 68, "team": "away", "off": 10, "on": 18},
        {"minute": 69, "team": "away", "off": 7, "on": 16},
        {"minute": 80, "team": "away", "off": 8, "on": 20},
    ],
    "goals": [
        {"minute": 18, "team": "home", "scorer": "Riccio", "assist": "Pereyra", "own_goal": False},
        {"minute": 34, "team": "home", "scorer": "Mané", "assist": "Chiummariello", "own_goal": False},
        {"minute": 70, "team": "home", "scorer": "Esposito", "assist": "Baridò", "own_goal": False},
        {"minute": 72, "team": "away", "scorer": "Longhi", "assist": "Vannucci", "own_goal": False},
    ],
    "cards": [
        {"minute": 55, "team": "away", "player": "Vignali", "colour": "yellow"},
        {"minute": 84, "team": "home", "player": "Esposito", "colour": "yellow"},
        {"minute": "90+5", "team": "away", "player": "Sartori", "colour": "yellow"},
    ],
}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def post(self, url, json=None, headers=None):  # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResp({"choices": [{"message": {"content": self.content}}],
                         "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "cost": 0.0}})


def fake_reader(content=None):
    content = content if content is not None else "```json\n" + json.dumps(MODEL_FACTS) + "\n```"
    return ms.SheetReader(api_key="", client=FakeClient(content))


# --- rendering + reading ------------------------------------------------------------------


def test_render_image_and_pdf_pages():
    data = FIXTURE_IMG.read_bytes()
    pages = ms.render_pages(data, "sheet.jpg")
    assert len(pages) == 1 and pages[0][:8] == b"\x89PNG\r\n\x1a\n"

    from PIL import Image

    buf = io.BytesIO()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.save(buf, "PDF", save_all=True, append_images=[img.copy()])  # 2-page "scanned" PDF
    pdf_pages = ms.render_pages(buf.getvalue(), "distinta.pdf")
    assert len(pdf_pages) == 2 and all(p[:4] == b"\x89PNG" for p in pdf_pages)


def test_reader_request_shape_and_parse():
    reader = fake_reader()
    pages = ms.render_pages(FIXTURE_IMG.read_bytes(), "x.jpg")
    raw = reader.read(pages, hint="home = Napoli, away = Spezia.")
    call = reader._client.calls[0]
    body = call["json"]
    assert call["url"].endswith("/chat/completions")
    assert body["model"] == "google/gemini-2.5-flash"
    assert body["response_format"]["json_schema"]["strict"] is True
    parts = body["messages"][1]["content"]
    assert any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts)
    assert "Authorization" not in call["headers"]  # no key in tests
    facts, issues = ms.validate_facts(raw)
    assert issues == []
    assert [g["minute"] for g in facts["goals"]] == [18, 34, 70, 72]
    assert facts["cards"][-1]["minute"] == 95


def test_reader_disabled_without_url(monkeypatch):
    monkeypatch.delenv("TAGGER_API_URL", raising=False)
    with pytest.raises(RuntimeError):
        ms.SheetReader().read([b"x"])


def test_validate_facts_coerces_and_flags():
    facts, issues = ms.validate_facts({
        "teams": {"home": "Napoli", "away": "Spezia"},
        "lineups": {"home": [{"number": "10", "name": "Riccio"}, {"number": 10, "name": "dup"}]},
        "goals": [{"minute": "18'", "team": "Napoli", "scorer": "10", "assist": None},
                  {"minute": "abc", "team": "home", "scorer": 1}],
        "cards": [{"minute": 5, "team": "Spezia", "player": 4, "colour": "giallo"},
                  {"minute": 6, "team": "away", "player": 4, "colour": "blue"}],
    })
    assert facts["home_team"] == "Napoli"
    assert facts["goals"] == [{"minute": 18.0, "team": "home", "scorer": 10, "assist": None, "own_goal": False}]
    assert facts["cards"][0]["colour"] == "yellow" and facts["cards"][0]["team"] == "away"
    assert any("twice" in i for i in issues) and any("minute" in i for i in issues) and any("colour" in i for i in issues)
    assert ms.parse_minute("45+2") == 47 and ms.parse_minute(None) is None


def test_lineup_and_on_pitch():
    facts, _ = ms.validate_facts(MODEL_FACTS)
    lu = ms.lineup_doc(facts)
    assert ms.on_pitch(lu, "home", 22, 30) is False      # Esposito comes on at 59'
    assert ms.on_pitch(lu, "home", 22, 70) is True
    assert ms.on_pitch(lu, "home", 5, 75) is False       # Branchizio off at 59'
    assert ms.on_pitch(lu, "home", 10, 10) is True
    assert ms.on_pitch(lu, "home", 13, 50) is False      # unused sub
    assert ms.on_pitch({"players": []}, "home", 10, 10) is None


# --- applying ----------------------------------------------------------------------------

LAG = 120.0  # the clips' match clock runs 2 minutes behind the real clock


def ev(etype, team, minute, shirt=None, status="auto", **attrs):
    return {"type": etype, "team": team, "shirt": shirt, "t_match_seconds": ms.minute_to_seconds(minute) - LAG,
            "attributes": attrs, "confidence": 0.9, "review_status": status, "source": "ai",
            "review_reason": [], "issues": [], "clip_ids": [0]}


def seed(repo):
    events = [
        ev("goal", "home", 18, shirt=7),          # Riccio's goal, wrong shirt
        ev("goal", "home", 34, shirt=11),         # Mané, correct
        ev("goal", "away", 50, shirt=9),          # phantom
        ev("goal", "away", 72, shirt=4),          # Longhi
        # Esposito's 70' goal was missed by the tagger
        ev("card", "away", 55, shirt=5, color="yellow"),
        ev("card", "home", 40, shirt=6, color="red"),  # phantom red card
        ev("pass", "home", 30, shirt=22, completed=True),  # Esposito not on yet -> attribution cleared
        ev("pass", "home", 20, shirt=10, completed=True),  # Riccio on the pitch -> name filled
        ev("pass", "away", 60, shirt=8, completed=False),
    ]
    repo.replace_ai_events(MID, events)


def test_apply_napoli_spezia():
    repo = FileEventRepo()
    seed(repo)
    before = repo.list_events(MID)
    out = ms.apply_facts(MID, MODEL_FACTS, repo=repo)
    rep, stats = out["report"], out["stats"]

    # clock re-anchored from goal times: +120 s in both halves
    assert rep["clock"]["offsets"] == {"1": LAG, "2": LAG}
    assert rep["shifted"] == len(before)

    events = repo.list_events(MID)
    live_goals = sorted((e for e in events if e["type"] == "goal" and e["review_status"] != "rejected"),
                        key=lambda e: e["t_match_seconds"])
    assert [(e["team"], e["shirt"], e["player"]) for e in live_goals] == [
        ("home", 10, "Riccio"), ("home", 11, "Mané"), ("home", 22, "Esposito"), ("away", 4, "Longhi")]
    assert [round(e["t_match_seconds"] / 60) for e in live_goals] == [18, 34, 70, 72]
    added = [e for e in live_goals if e["shirt"] == 22][0]
    assert added["source"] == "human" and ms.SHEET_TAG in added["review_reason"] and added["review_status"] == "confirmed"
    assert len(rep["goals"]["rejected"]) == 1 and len(rep["goals"]["added"]) == 1 and len(rep["goals"]["corrected"]) == 3
    assert [e["attributes"].get("assist_player") for e in live_goals] == ["Pereyra", "Chiummariello", "Baridò", "Vannucci"]

    # cards: Vignali matched, phantom red removed, 2 added
    assert len(rep["cards"]["corrected"]) == 1 and len(rep["cards"]["rejected"]) == 1 and len(rep["cards"]["added"]) == 2

    # on-pitch constraint
    p22 = next(e for e in events if e["type"] == "pass" and e["team"] == "home" and round(e["t_match_seconds"] / 60) == 30)
    assert p22["shirt"] is None and p22["review_status"] == "pending"
    p10 = next(e for e in events if e["type"] == "pass" and e["shirt"] == 10)
    assert p10["player"] == "Riccio"

    # stats recomputed from the corrected events + sheet lineup
    t = stats["teams"]
    assert (t["home"]["goals"], t["away"]["goals"]) == (3, 1)
    assert (t["home"]["yellow_cards"], t["home"]["red_cards"], t["away"]["yellow_cards"]) == (1, 0, 2)
    players = {(p["team"], p["shirt"]): p for p in stats["players"]}
    assert players[("home", 9)]["assists"] == 1 and players[("home", 8)]["assists"] == 1
    assert players[("home", 20)]["assists"] == 1 and players[("away", 8)]["assists"] == 1
    assert players[("home", 22)]["goals"] == 1 and players[("home", 22)]["minutes"] == pytest.approx(36.0)  # 59'-95'
    assert players[("home", 1)]["conceded"] == 1
    assert store.read_doc(MID, "stats")["teams"]["home"]["goals"] == 3
    assert store.read_doc(MID, "lineup")["source"] == "match_sheet"
    assert any(c["action"] == "clock_offset" for c in repo.list_corrections(MID))


def test_apply_is_idempotent():
    repo = FileEventRepo()
    seed(repo)
    ms.apply_facts(MID, MODEL_FACTS, repo=repo)
    first = [(e["id"], e["type"], e["team"], e["shirt"], e["t_match_seconds"], e["review_status"]) for e in repo.list_events(MID)]
    rep2 = ms.apply_facts(MID, MODEL_FACTS, repo=repo)["report"]
    second = [(e["id"], e["type"], e["team"], e["shirt"], e["t_match_seconds"], e["review_status"]) for e in repo.list_events(MID)]
    assert first == second
    assert rep2["shifted"] == 0 and rep2["goals"]["added"] == [] and rep2["goals"]["rejected"] == []


def test_apply_without_tags_adds_everything():
    repo = FileEventRepo()
    out = ms.apply_facts(MID, MODEL_FACTS, repo=repo)
    assert out["report"]["clock"]["offsets"] == {}
    assert (out["stats"]["teams"]["home"]["goals"], out["stats"]["teams"]["away"]["goals"]) == (3, 1)


# --- API: upload -> draft (nothing applied) -> confirm ---------------------------------------


def test_api_upload_draft_then_confirm(monkeypatch):
    from statman.api import app

    repo = FileEventRepo()
    seed(repo)
    fake = FakeClient(json.dumps(MODEL_FACTS))
    real_init = ms.SheetReader.__init__

    def init(self, **kw):
        real_init(self, **{**kw, "client": fake})

    monkeypatch.setattr(ms.SheetReader, "__init__", init)
    client = TestClient(app)
    snapshot = repo.list_events(MID)

    r = client.post(f"/api/autotag/matches/{MID}/matchsheet/upload",
                    files={"file": ("distinta.jpg", FIXTURE_IMG.read_bytes(), "image/jpeg")})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "draft" and doc["pages"] == 1 and len(doc["facts"]["goals"]) == 4
    assert len(fake.calls) == 1
    assert repo.list_events(MID) == snapshot  # nothing applied before confirmation
    assert client.get(f"/api/autotag/matches/{MID}/matchsheet/pages/1.png").status_code == 200
    assert client.get(f"/api/autotag/matches/{MID}/matchsheet").json()["status"] == "draft"

    # user edits: drop the 90+5 card in the check screen, then confirms
    edited = {**doc["facts"], "cards": doc["facts"]["cards"][:2]}
    r = client.post(f"/api/autotag/matches/{MID}/matchsheet/confirm", json={"facts": edited, "reviewer": "fp"})
    assert r.status_code == 200, r.text
    assert r.json()["report"]["score"] == {"home": 3, "away": 1}
    assert client.get(f"/api/autotag/matches/{MID}/matchsheet").json()["status"] == "confirmed"
    stats = client.get(f"/api/autotag/matches/{MID}/stats").json()
    assert stats["teams"]["away"]["yellow_cards"] == 1


def test_api_manual_entry_and_errors():
    from statman.api import app

    client = TestClient(app)
    r = client.put(f"/api/autotag/matches/{MID}/matchsheet", json={"facts": MODEL_FACTS})
    assert r.status_code == 200 and r.json()["source"] == "manual" and r.json()["status"] == "draft"
    assert client.post(f"/api/autotag/matches/{MID}/matchsheet/confirm", json={}).status_code == 400
    assert client.get("/matchsheet").status_code == 200


def test_api_upload_reader_not_configured(monkeypatch):
    from statman.api import app

    monkeypatch.delenv("TAGGER_API_URL", raising=False)
    r = TestClient(app).post(f"/api/autotag/matches/{MID}/matchsheet/upload",
                             files={"file": ("d.jpg", FIXTURE_IMG.read_bytes(), "image/jpeg")})
    assert r.status_code == 503
