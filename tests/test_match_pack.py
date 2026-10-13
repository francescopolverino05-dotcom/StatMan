"""Phase-1 match pack: facts → fact-sourced sheet."""

from __future__ import annotations

from pathlib import Path

import pytest

from statman.match_pack import store
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts, parse_facts_text
from statman.match_pack.pipeline import (
    attach_video_bytes,
    compute_pack,
    create_pack,
    put_facts,
    put_facts_file,
    save_formation_pdf,
)
from statman.match_pack.sheet_from_facts import sheet_from_facts


@pytest.fixture()
def pack_root(tmp_path, monkeypatch):
    root = tmp_path / "match_packs"
    monkeypatch.setattr(store, "ROOT", root)
    store.ensure_root()
    return root


def test_normalize_example_facts():
    facts = normalize_facts(EXAMPLE_FACTS)
    assert facts["home"]["team_name"] == "Belgium"
    assert facts["away"]["formation"] == "3-5-2"
    assert len(facts["home"]["lineup"]) == 11
    assert sum(1 for e in facts["events"] if e["type"] == "goal") == 2


def test_sheet_from_facts_counts_goals_and_cards():
    facts = normalize_facts(EXAMPLE_FACTS)
    sheet = sheet_from_facts(facts, pack_id="demo")
    assert sheet["match"]["home_score"] == 2
    assert sheet["match"]["away_score"] == 0
    home, away = sheet["teams"]
    assert home["goals"] == 2
    assert home["yellow_cards"] == 0
    assert away["yellow_cards"] == 1
    assert home["corners"]["total"] == 4
    assert away["free_kicks"] == 7
    assert home["possession_pct"] is None
    assert home["ppda"] is None
    assert home["provenance"]["goals"]["status"] == "fact"
    assert home["provenance"]["possession_pct"]["status"] == "pending"
    assert "goals" in sheet["source"]["coverage"]["fact"]
    assert "ppda" in sheet["source"]["coverage"]["pending_later_phases"]
    lukaku = next(p for p in sheet["players"] if p["player_name"] == "Romelu Lukaku")
    meunier = next(p for p in sheet["players"] if p["player_name"] == "Thomas Meunier")
    assert lukaku["goals"] == 0
    assert meunier["goals"] == 1


def test_create_put_compute_roundtrip(pack_root):
    meta = create_pack(home_team="Home FC", away_team="Away United")
    assert meta["pack_id"]
    assert (pack_root / meta["pack_id"] / "pack.json").exists()
    put_facts(meta["pack_id"], EXAMPLE_FACTS)
    done = compute_pack(meta["pack_id"])
    assert done["status"] == "sheet_ready"
    assert done["sheet"]["match"]["home_score"] == 2
    assert done["coverage"]["fact_event_counts"]["goals"] == 2


def test_formation_pdf_and_video_attach(pack_root, tmp_path):
    meta = create_pack()
    pack_id = meta["pack_id"]
    # Minimal PDF
    try:
        from pypdf import PdfWriter
    except ImportError:
        pytest.skip("pypdf missing")
    pdf_path = tmp_path / "home_xi.pdf"
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with pdf_path.open("wb") as fh:
        w.write(fh)
    with pdf_path.open("rb") as fh:
        save_formation_pdf(pack_id, "home", fh, "home_xi.pdf")
    meta = store.read_meta(pack_id)
    assert meta["formation"]["home"]["filename"] == "home_xi.pdf"
    assert meta["formation"]["home"]["extract"]["ok"] is True

    vid = tmp_path / "match.mp4"
    vid.write_bytes(b"\x00\x00fake-video-bytes-for-test")
    with vid.open("rb") as fh:
        attach_video_bytes(pack_id, fh, "match.mp4")
    meta = store.read_meta(pack_id)
    assert meta["video"]["status"] == "ready"
    assert meta["video"]["size_bytes"] == vid.stat().st_size


def test_rejects_bad_event_type():
    with pytest.raises(ValueError, match="type must be"):
        normalize_facts(
            {
                "home": {"team_name": "A"},
                "away": {"team_name": "B"},
                "events": [{"type": "var_review", "minute": 10, "team": "home"}],
            }
        )


def test_napoli_pisa_primavera_sample_facts_validate():
    sample = (
        Path(__file__).resolve().parents[1]
        / "samples"
        / "napoli_pisa_primavera2_2026-10-10_facts.json"
    )
    assert sample.exists()
    facts = parse_facts_text(sample.read_bytes())
    sheet = sheet_from_facts(facts, pack_id="np")
    assert "Primavera 2" in (sheet["match"]["competition"] or "")
    assert sheet["match"]["home_score"] == 1
    assert sheet["match"]["away_score"] == 0
    assert sheet["match"]["home_formation"] == "3-4-2-1"
    assert sheet["match"]["away_formation"] == "4-4-2"
    assert any(
        e["type"] == "goal" and e.get("player_name") == "Mané" for e in sheet["events"]
    )
    assert any(
        e["type"] == "substitution"
        and e.get("player_in") == "Mané"
        and e.get("minute") == 70
        for e in sheet["events"]
    )


def test_bad_facts_file_does_not_wipe_prior(pack_root, tmp_path):
    meta = create_pack()
    pack_id = meta["pack_id"]
    put_facts(pack_id, EXAMPLE_FACTS)
    before = store.read_meta(pack_id)["facts"]["home"]["team_name"]
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with bad.open("rb") as fh:
        with pytest.raises(ValueError, match="Invalid JSON"):
            put_facts_file(pack_id, fh, "broken.json")
    after = store.read_meta(pack_id)
    assert after["facts"]["home"]["team_name"] == before
    assert after.get("error")
    assert after.get("facts_upload_path")
