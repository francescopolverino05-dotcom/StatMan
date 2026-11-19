"""Structural checks for the Docker Compose stack (no daemon required)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_stack_wires_db_api_and_dashboard() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "container_name: enjoystats-db" in compose
    assert "container_name: enjoystats-api" in compose
    assert "container_name: enjoystats-dashboard" in compose
    assert (
        "./storage/postgres_tables.sql:/docker-entrypoint-initdb.d/01-postgres_tables.sql"
        in compose
    )
    assert "condition: service_healthy" in compose
    assert '"8000:8000"' in compose
    assert '"8501:8501"' in compose
    assert "ENJOYSTATS_API_URL" in compose
    assert "postgres_data" in compose
    assert "pg_isready" in compose
    assert "/health" in compose
    assert "/_stcore/health" in compose


def test_dockerfiles_are_multistage_slim_python() -> None:
    api = (ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    dashboard = (ROOT / "Dockerfile.dashboard").read_text(encoding="utf-8")
    assert "python:3.11-slim AS builder" in api
    assert "python:3.11-slim AS runtime" in api
    assert "python:3.11-slim AS builder" in dashboard
    assert "python:3.11-slim AS runtime" in dashboard
    assert 'CMD ["python", "-m", "api.main"]' in api
    assert "streamlit" in dashboard
    assert "http://api:8000" in dashboard
