"""Full pipeline step registry."""

from __future__ import annotations

from statman.match_pack.full_pipeline import STEPS, _pct_for


def test_pipeline_steps_cover_board_fill():
    ids = [s[0] for s in STEPS]
    assert ids[0] == "film"
    assert ids[-1] == "xg_ppda"
    assert "shots" in ids and "actions" in ids
    assert abs(sum(w for _, _, w in STEPS) - 100.0) < 1e-6


def test_pipeline_pct_monotonic():
    assert _pct_for("film", 0.0) == 0
    assert _pct_for("film", 1.0) == 25
    assert _pct_for("xg_ppda", 1.0) == 100
    assert _pct_for("tracking", 0.0) < _pct_for("shots", 0.0)
