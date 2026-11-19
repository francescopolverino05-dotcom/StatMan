"""End-to-end HTTP test for the 5-second mock attacking sequence."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from api.main import create_app
from tests.fakes import InMemoryProfileStore
from tests.mock_match_simulator import (
    PLAYMAKER_ID,
    STRIKER_ID,
    SimulatorError,
    build_attacking_sequence,
    ensure_api_running,
    run_simulation,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_api_url() -> str:
    """Serve the FastAPI app over real HTTP with an in-memory profile store."""

    application = create_app(aggregator=InMemoryProfileStore())
    port = _free_port()
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="on",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            if server.started:
                try:
                    with httpx.Client() as client:
                        ensure_api_running(client, base_url, timeout_s=0.25)
                    break
                except SimulatorError:
                    time.sleep(0.05)
            else:
                time.sleep(0.05)
        else:
            raise RuntimeError("Timed out waiting for the in-process FastAPI server.")
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_attacking_sequence_script_has_five_seconds() -> None:
    frames = build_attacking_sequence()
    assert [frame.second for frame in frames] == [1, 2, 3, 4, 5]


def test_simulator_requires_a_running_server() -> None:
    with httpx.Client() as client:
        with pytest.raises(SimulatorError, match="not running"):
            ensure_api_running(client, "http://127.0.0.1:1", timeout_s=0.2)


def test_five_second_attacking_move_round_trips_http(live_api_url: str) -> None:
    with httpx.Client() as client:
        report = run_simulation(client, live_api_url, delay_seconds=0.0)

    playmaker = report.playmaker
    striker = report.striker
    assert playmaker.player_id == PLAYMAKER_ID
    assert striker.player_id == STRIKER_ID
    assert playmaker.distribution.passes.success_rate == 1.0
    assert playmaker.distribution.passes.total == 3
    assert striker.offensive.goals == 1
    assert striker.offensive.shots_on_target == 1
    assert striker.offensive.shots_inside_penalty_area == 1
    assert striker.defensive.ground_duels.success_rate == 1.0
    assert "100% passing accuracy" in report.summary
    assert "1 goal" in report.summary
    assert "100% duel win rate" in report.summary
    assert "PIPELINE VERIFIED" in report.summary
