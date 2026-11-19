"""Pitch-map event extraction and PNG rendering (uses StatsBomb open data)."""

from __future__ import annotations

from statman.load import load_match
from statman.maps import extract_map_events, render_map_png


def test_extract_and_render_belgium_england_maps() -> None:
    bundle = load_match(8657)
    events = extract_map_events(bundle)
    assert events["match"]["home_team"] == "Belgium"
    assert events["shots"], "expected StatsBomb shots with xG"
    assert any(s.get("xg") and s["xg"] > 0 for s in events["shots"])
    assert events["progressive_passes"]
    assert events["defence"]
    assert all("x" in s and "y" in s for s in events["shots"])
    assert all("end_x" in p for p in events["progressive_passes"])

    for kind in ("shots", "progressive", "defence"):
        png = render_map_png(8657, kind=kind)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(png) > 5_000
