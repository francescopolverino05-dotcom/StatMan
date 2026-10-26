"""Semi-automatic tagging: items confirmed in /tag become authoritative events via the hand-tag path."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from statman.autotag import semi, store
from statman.autotag.handtags import clock_to_seconds, load_files, parse_line
from statman.autotag.repo import FileEventRepo
from statman.autotag.stats import match_stats

D = Path(__file__).parent / "fixtures" / "napoli_spezia_tags60"
HAND = Path("/workspace/at-test/hand.txt")
TEAMS = {"Napoli": "home", "Spezia": "away"}
SETTINGS = {"home_name": "Napoli", "away_name": "Spezia", "segments": [{"video_start": 0, "match_start": 0}]}


@pytest.fixture(autouse=True)
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    yield tmp_path


def line_to_item(line: str, k: int) -> dict | None:
    if parse_line(line, TEAMS) is None or "GAP" in line.split("|")[:3]:
        return None
    p = [x.strip() for x in line.split("|")] + [""] * 10
    pt = lambda s: [float(v) for v in s.split(",")] if "," in s else [None, None]  # noqa: E731
    (x1, y1), (x2, y2) = pt(p[6]), pt(p[7])
    return {"id": f"h{k}", "t_video": clock_to_seconds(p[0]), "status": "done", "team": TEAMS[p[1]], "code": p[2],
            "shirt": int(p[4]) if p[4].isdigit() else None, "outcome": p[5].lower() or None,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2, "detail": p[8] or None}


def items_from(lines):
    return [i for k, l in enumerate(lines) if (i := line_to_item(l, k))]


def team_stats(events):
    s = match_stats(events)
    keys = ("passes", "passes_completed", "possession_pct", "progressive_passes", "progressive_passes_completed",
            "ppda_opponent_passes", "ppda_defensive_actions", "shots", "shots_on_target")
    return {t: {k: s["teams"][t].get(k) for k in keys} for t in ("home", "away")}, s


def test_clean_item_validation():
    ok = semi.clean_item({"t_video": 3.456, "code": "pass", "team": "home", "x1": 10, "y1": 20, "shirt": "7"})
    assert ok["code"] == "PASS" and ok["t_video"] == 3.46 and ok["shirt"] == 7 and ok["status"] == "todo"
    for bad in ({"t_video": 1, "code": "NOPE"}, {"t_video": 1, "team": "x"}, {"t_video": 1, "x1": 120},
                {"t_video": 1, "status": "done", "code": "PASS"}, {"t_video": 1, "status": "maybe"}):
        with pytest.raises(ValueError):
            semi.clean_item(bad)


def test_video_to_match_segments():
    segs = [{"video_start": 0, "match_start": 0}, {"video_start": 3000, "match_start": 2700}]
    assert semi.video_to_match(10, segs) == 10
    assert semi.video_to_match(3010, segs) == 2710
    assert semi.clock(2710) == "45:10"


def test_import_moments_and_save_sync_no_duplicates():
    repo = FileEventRepo()
    out = semi.import_moments("m1", {"moments": [{"t": 5.0, "possession_team": "home", "kind": "x"},
                                                  {"t": 5.1}, {"t": 9.0, "team": "zzz"}]})
    items = out["items"]
    assert [i["t_video"] for i in items] == [5.0, 9.0]  # 5.1 is within 0.3 s of 5.0
    assert items[0]["team_suggestion"] == "home" and items[1]["team_suggestion"] is None
    assert out["confirmed"] == 0 and not repo.list_events("m1")  # suggestions are never counted
    items[0].update(status="done", team="home", code="PASS", outcome="success", x1=40, y1=50, x2=80, y2=50)
    for _ in range(3):
        r = semi.save_session("m1", {"settings": SETTINGS, "items": items}, repo=repo)
    assert r["confirmed"] == 1
    evs = repo.list_events("m1")
    assert len(evs) == 1 and evs[0]["source"] == "human" and evs[0]["review_status"] == "confirmed"
    items[1].update(status="deleted")
    items[0].update(status="todo")
    semi.save_session("m1", {"items": items}, repo=repo)
    assert repo.list_events("m1") == []
    # re-import keeps confirmed/deleted items, replaces only open detector moments
    items[0].update(status="done")
    semi.save_session("m1", {"items": items}, repo=repo)
    again = semi.import_moments("m1", [{"t": 20}])
    assert [i["t_video"] for i in again["items"]] == [5.0, 9.0, 20.0]


def test_semi_events_do_not_touch_other_human_events():
    repo = FileEventRepo()
    repo.add_event("m2", {"code": "PASS", "type": "pass", "team": "home", "source": "human",
                          "review_status": "confirmed", "t_match_seconds": 1})
    before = len(repo.list_events("m2"))
    semi.save_session("m2", {"settings": SETTINGS, "items": [
        {"t_video": 3, "status": "done", "team": "away", "code": "SHOT", "outcome": "on"}]}, repo=repo)
    semi.save_session("m2", {"items": [{"t_video": 3, "status": "done", "team": "away", "code": "SHOT", "outcome": "on"}]}, repo=repo)
    assert len(repo.list_events("m2")) == before + 1


def test_csv_and_tags_export():
    semi.save_session("m3", {"settings": SETTINGS, "items": [
        {"t_video": 61, "status": "done", "team": "home", "code": "PASS", "shirt": 10, "outcome": "fail",
         "x1": 50, "y1": 50, "x2": 70, "y2": 30}, {"t_video": 70}]}, repo=FileEventRepo())
    rows = semi.export_csv("m3").splitlines()
    assert rows[0].startswith("clock,match_seconds") and len(rows) == 2
    assert rows[1].startswith("01:01,61.0,61.0,home,Napoli,PASS,10,fail,50.0,50.0,70.0,30.0")
    assert semi.export_tags("m3") == "01:01|Napoli|PASS||10|fail|50,50|70,30||1\n"


def test_confirm_path_matches_hand_16_19():
    lines = [l for l in (D / "16-20.txt").read_text(encoding="utf-8").splitlines()
             if (t := clock_to_seconds(l.split("|")[0])) is not None and 16 * 60 <= t < 19 * 60]
    if HAND.exists():
        assert len(items_from(lines)) == len(items_from(HAND.read_text(encoding="utf-8").splitlines()))
    repo = FileEventRepo()
    r = semi.save_session("hand", {"settings": SETTINGS, "items": items_from(lines)}, repo=repo)
    hand = [{**e, "review_status": "confirmed"} for l in lines if (e := parse_line(l, TEAMS)) and e.get("type") != "gap"]
    assert r["confirmed"] == len(hand) > 50
    got, s = team_stats(repo.list_events("hand"))
    want, _ = team_stats(hand)
    assert got == want
    assert all(v["status"] != "estimated" for k, v in s["stat_flags"].items() if k != "xg")  # xG is a model estimate by definition


def test_full_match_through_semi_reproduces_hand_numbers():
    ev = load_files(sorted(D.glob("*.txt")), TEAMS, supplements=[
        (D / "old" / "73-77.txt", lambda e: e["code"] == "SHOT" and e["clock"] in ("75:28", "76:48"))])
    # Rebuild the deduplicated hand lines as items (one per loaded event, incl. gaps kept as events by stats)
    items, gaps = [], []
    for k, e in enumerate(ev):
        if e["code"] == "GAP":
            gaps.append(e)
            continue
        items.append({"id": f"f{k}", "t_video": e["t_match_seconds"], "status": "done", "team": e["team"],
                      "code": e["code"], "shirt": e.get("shirt"), "outcome": e.get("outcome"),
                      "x1": e.get("x"), "y1": e.get("y"), "x2": e.get("x2"), "y2": e.get("y2"),
                      "detail": e.get("detail")})
    repo = FileEventRepo()
    semi.save_session("full", {"settings": SETTINGS, "items": items}, repo=repo)
    s = match_stats(repo.list_events("full") + gaps)
    h, a = s["teams"]["home"], s["teams"]["away"]
    assert (h["passes_completed"], h["passes"]) == (946, 1131)
    assert (a["passes_completed"], a["passes"]) == (676, 846)
    assert h["possession_pct"] == 57.2
    assert (h["progressive_passes_completed"], h["progressive_passes"]) == (100, 242)
    assert (a["progressive_passes_completed"], a["progressive_passes"]) == (74, 201)


def test_api_endpoints():
    from statman.api import app
    c = TestClient(app)
    assert c.get("/tag").status_code == 200
    g = c.get("/api/semi/apim").json()
    assert g["items"] == [] and "PASS" in str(g)
    assert c.post("/api/semi/apim/moments", json={"moments": [{"t": 12.5, "team": "away"}]}).status_code == 200
    items = c.get("/api/semi/apim").json()["items"]
    items[0].update(status="done", team="away", code="TACKLE", outcome="success", x1=30, y1=40)
    r = c.put("/api/semi/apim", json={"settings": SETTINGS, "items": items})
    assert r.status_code == 200 and r.json()["confirmed"] == 1
    assert c.put("/api/semi/apim", json={"items": [{"t_video": 1, "status": "done"}]}).status_code == 400
    assert "TACKLE" in c.get("/api/semi/apim/events.csv").text
    assert "|Spezia|TACKLE|" in c.get("/api/semi/apim/tags.txt").text
    st = c.get("/api/autotag/matches/apim/stats?confirmed_only=true")
    assert st.status_code == 200
