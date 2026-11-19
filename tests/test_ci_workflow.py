"""Structural checks for the GitHub Actions CI workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_covers_lint_postgres_and_simulator() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert WORKFLOW.is_file()
    assert "actions/checkout@v4" in text
    assert "actions/setup-python@v5" in text
    assert 'python-version: "3.11"' in text
    assert "cache: pip" in text
    assert "ubuntu-latest" in text
    assert "flake8" in text
    assert "black" in text
    assert "postgres:16-alpine" in text
    assert "storage/postgres_tables.sql" in text
    assert "requirements.txt" in text
    assert "python -m api.main" in text
    assert "tests/mock_match_simulator.py" in text
    assert "branches: [main]" in text
    assert "pull_request:" in text
