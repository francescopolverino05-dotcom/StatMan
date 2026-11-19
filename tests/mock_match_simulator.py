#!/usr/bin/env python3
"""Simulate a live 5-second attacking sequence against the AutoData API.

The script tags Pydantic :class:`~data_models.events.MatchEvent` objects,
folds them through :class:`~analytics.stats_collector.PlayerStatsCollector`,
and upserts the resulting :class:`~data_models.player_stats.PlayerMatchProfile`
documents to FastAPI.

Run against a live server (from the repository root)::

    python tests/mock_match_simulator.py --base-url http://127.0.0.1:8000

The process exits non-zero if the API is unreachable or the consolidated
metrics do not match the expected attacking-move outcome.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.stats_collector import PlayerStatsCollector, new_collector
from config.pitch_config import PenaltyBox, PitchThird, map_player_coordinates, map_to_pitch_third
from data_models.events import EventType, MatchEvent, ShotOutcome
from data_models.player_stats import PlayerMatchProfile

DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:8000"
REQUEST_TIMEOUT_S: Final[float] = 5.0

MATCH_ID: Final[UUID] = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEAM_ID: Final[UUID] = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PLAYMAKER_ID: Final[UUID] = UUID("11111111-1111-1111-1111-111111111111")
STRIKER_ID: Final[UUID] = UUID("22222222-2222-2222-2222-222222222222")
DEFENDER_ID: Final[UUID] = UUID("33333333-3333-3333-3333-333333333333")

PLAYMAKER_NUMBER: Final[int] = 8
STRIKER_NUMBER: Final[int] = 9
PLAYMAKER_POSITION: Final[str] = "CAM"
STRIKER_POSITION: Final[str] = "ST"


class SimulatorError(RuntimeError):
    """Raised when the live sequence cannot be ingested or verified."""


@dataclass(frozen=True, slots=True)
class SecondScript:
    """One match-second of the attacking move."""

    second: int
    description: str
    event: MatchEvent


@dataclass(frozen=True, slots=True)
class SimulationReport:
    """GET-verified player profiles plus a printable summary."""

    playmaker: PlayerMatchProfile
    striker: PlayerMatchProfile
    summary: str


def build_attacking_sequence() -> list[SecondScript]:
    """Return the five-second playmaker-to-striker attacking script.

    Seconds 1–3 are successful passes that travel from the middle third into
    the final third. Second 4 is a ground duel won by the striker. Second 5
    is a shot on target from ``(88, 50)`` that results in a goal.
    """

    passes = (
        ((42.0, 48.0), (50.0, 50.0), "Playmaker threads a short pass in midfield"),
        ((50.0, 50.0), (60.0, 49.0), "Playmaker advances the striker toward the final third"),
        ((62.0, 50.0), (78.0, 52.0), "Playmaker releases the striker into the final third"),
    )
    frames: list[SecondScript] = []
    for index, ((start_x, start_y), (end_x, end_y), description) in enumerate(passes, start=1):
        start_third = map_to_pitch_third(start_x, start_y)
        end_third = map_to_pitch_third(end_x, end_y)
        if index < 3 and start_third is not PitchThird.MIDDLE:
            raise SimulatorError(f"Pass {index} must start in the middle third, got {start_third}.")
        if index == 3 and (
            start_third is not PitchThird.MIDDLE or end_third is not PitchThird.FINAL
        ):
            raise SimulatorError("Pass 3 must travel from the middle third into the final third.")
        frames.append(
            SecondScript(
                second=index,
                description=description,
                event=_pass_event(
                    second=index, start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y
                ),
            )
        )

    frames.append(
        SecondScript(
            second=4,
            description="Defender engages the striker; striker wins the ground duel",
            event=_ground_duel_won_by_striker(second=4, x=80.0, y=50.0),
        )
    )

    shot_location = map_player_coordinates(88.0, 50.0)
    if shot_location.penalty_box is not PenaltyBox.ATTACKING:
        raise SimulatorError("Shot at (88, 50) must sit inside the attacking penalty area.")
    frames.append(
        SecondScript(
            second=5,
            description="Striker shoots on target from the penalty area and scores",
            event=_striker_goal(second=5, x=88.0, y=50.0),
        )
    )
    return frames


def _base_event(**overrides: Any) -> MatchEvent:
    payload: dict[str, Any] = {
        "match_id": MATCH_ID,
        "team_id": TEAM_ID,
        "period": 1,
        "minute": 0,
        "attacking_left_to_right": True,
        "successful": True,
    }
    payload.update(overrides)
    return MatchEvent.model_validate(payload)


def _pass_event(
    *,
    second: int,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> MatchEvent:
    return _base_event(
        player_id=PLAYMAKER_ID,
        second=second,
        event_type=EventType.PASS,
        x=start_x,
        y=start_y,
        end_x=end_x,
        end_y=end_y,
        successful=True,
        is_progressive=True,
    )


def _ground_duel_won_by_striker(*, second: int, x: float, y: float) -> MatchEvent:
    """Tag the duel on the striker as won; the defender is the opponent."""

    _ = DEFENDER_ID
    return _base_event(
        player_id=STRIKER_ID,
        second=second,
        event_type=EventType.GROUND_DUEL,
        x=x,
        y=y,
        successful=True,
    )


def _striker_goal(*, second: int, x: float, y: float) -> MatchEvent:
    return _base_event(
        player_id=STRIKER_ID,
        second=second,
        event_type=EventType.SHOT,
        x=x,
        y=y,
        end_x=100.0,
        end_y=50.0,
        successful=True,
        is_goal=True,
        shot_outcome=ShotOutcome.ON_TARGET,
    )


def kickoff_collectors() -> tuple[PlayerStatsCollector, PlayerStatsCollector]:
    """Return empty collectors for the playmaker (CAM) and striker (ST)."""

    playmaker = new_collector(
        match_id=MATCH_ID,
        player_id=PLAYMAKER_ID,
        team_id=TEAM_ID,
        jersey_number=PLAYMAKER_NUMBER,
        position=PLAYMAKER_POSITION,
    )
    striker = new_collector(
        match_id=MATCH_ID,
        player_id=STRIKER_ID,
        team_id=TEAM_ID,
        jersey_number=STRIKER_NUMBER,
        position=STRIKER_POSITION,
    )
    return playmaker, striker


def profile_json(collector: PlayerStatsCollector) -> dict[str, Any]:
    """Dump a collector snapshot as a FastAPI-safe PlayerMatchProfile payload."""

    profile = PlayerMatchProfile.from_stats(collector.stats)
    return profile.model_dump(mode="json", exclude_computed_fields=True)


def ensure_api_running(
    client: httpx.Client,
    base_url: str,
    *,
    timeout_s: float = REQUEST_TIMEOUT_S,
) -> None:
    """Fail fast when the FastAPI process is not accepting requests.

    Args:
        client: Shared HTTP client.
        base_url: API origin, e.g. ``http://127.0.0.1:8000``.
        timeout_s: Per-request timeout.

    Raises:
        SimulatorError: If the OpenAPI document cannot be fetched.
    """

    url = f"{base_url.rstrip('/')}/openapi.json"
    try:
        response = client.get(url, timeout=timeout_s)
    except httpx.RequestError as exc:
        raise SimulatorError(
            "FastAPI server is not running at "
            f"{base_url}. Start it with `uvicorn api.main:app --host 0.0.0.0 --port 8000` "
            f"({exc})."
        ) from exc
    if response.status_code != 200:
        raise SimulatorError(
            f"FastAPI server at {base_url} responded {response.status_code} from /openapi.json."
        )
    try:
        title = response.json().get("info", {}).get("title", "")
    except ValueError as exc:
        raise SimulatorError("FastAPI OpenAPI document was not valid JSON.") from exc
    if "Football Analytics" not in str(title):
        raise SimulatorError(f"Unexpected OpenAPI title {title!r}; is this the AutoData API?")


def _raise_for_api_error(response: httpx.Response, *, action: str) -> None:
    if response.is_success:
        return
    detail = response.text
    try:
        payload = response.json()
        detail = str(payload.get("message") or payload)
    except ValueError:
        pass
    raise SimulatorError(f"{action} failed ({response.status_code}): {detail}")


def post_profile(client: httpx.Client, base_url: str, collector: PlayerStatsCollector) -> None:
    """Upsert one player's live profile."""

    url = f"{base_url.rstrip('/')}/api/v1/matches/{MATCH_ID}/players"
    response = client.post(url, json=profile_json(collector), timeout=REQUEST_TIMEOUT_S)
    _raise_for_api_error(response, action=f"POST {collector.stats.position} profile")


def _without_computed_fields(value: Any, *, parent_key: str | None = None) -> Any:
    """Drop GET-only computed keys so the payload round-trips into StrictModel."""

    computed = {"shot_accuracy", "failed", "success_rate"}
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if key in computed:
                continue
            if key == "total" and parent_key in {"blocks", "ball_recoveries", "ball_lost"}:
                continue
            cleaned[key] = _without_computed_fields(item, parent_key=key)
        return cleaned
    if isinstance(value, list):
        return [_without_computed_fields(item, parent_key=parent_key) for item in value]
    return value


def get_profile(client: httpx.Client, base_url: str, player_id: UUID) -> PlayerMatchProfile:
    """Load the consolidated profile the API stored for ``player_id``."""

    url = f"{base_url.rstrip('/')}/api/v1/matches/{MATCH_ID}/players/{player_id}"
    response = client.get(url, timeout=REQUEST_TIMEOUT_S)
    _raise_for_api_error(response, action=f"GET player {player_id}")
    return PlayerMatchProfile.model_validate(_without_computed_fields(response.json()))


def verify_consolidated_metrics(
    playmaker: PlayerMatchProfile,
    striker: PlayerMatchProfile,
) -> str:
    """Assert the expected end-of-move leaderboard and return a summary.

    Raises:
        SimulatorError: If passing accuracy, the goal, or duel rate is wrong.
    """

    playmaker_passes = playmaker.distribution.passes
    if playmaker_passes.total != 3 or playmaker_passes.success != 3:
        raise SimulatorError(
            "Playmaker expected 3/3 completed passes, got "
            f"{playmaker_passes.success}/{playmaker_passes.total}."
        )
    if playmaker_passes.success_rate != 1.0:
        raise SimulatorError(
            f"Playmaker passing accuracy is {playmaker_passes.success_rate:.0%}, expected 100%."
        )

    shot = striker.offensive
    if shot.goals != 1:
        raise SimulatorError(f"Striker expected 1 goal, got {shot.goals}.")
    if shot.shots_on_target != 1:
        raise SimulatorError(f"Striker expected 1 shot on target, got {shot.shots_on_target}.")
    if shot.shots_inside_penalty_area != 1:
        raise SimulatorError(
            "Striker expected 1 shot inside the penalty area, "
            f"got {shot.shots_inside_penalty_area}."
        )
    duels = striker.defensive.ground_duels
    if duels.total != 1 or duels.success != 1 or duels.success_rate != 1.0:
        raise SimulatorError(
            "Striker expected a 100% ground-duel win rate (1/1), "
            f"got {duels.success}/{duels.total}."
        )

    return format_summary(playmaker, striker)


def format_summary(playmaker: PlayerMatchProfile, striker: PlayerMatchProfile) -> str:
    """Render a terminal report from GET-verified profiles."""

    passes = playmaker.distribution.passes
    duels = striker.defensive.ground_duels
    shot = striker.offensive
    width = 72
    lines = [
        "=" * width,
        " EnjoyStats — live 5-second attacking sequence",
        "=" * width,
        f" Match ID     : {MATCH_ID}",
        f" Playmaker    : #{PLAYMAKER_NUMBER} {PLAYMAKER_POSITION}  ({PLAYMAKER_ID})",
        f" Striker      : #{STRIKER_NUMBER} {STRIKER_POSITION}   ({STRIKER_ID})",
        "-" * width,
        (
            f" Playmaker    : {passes.success_rate:.0%} passing accuracy "
            f"({passes.success}/{passes.total} completed)"
        ),
        (
            f" Striker      : {shot.goals} goal, {shot.shots_on_target} shot on target "
            f"inside the PA, {duels.success_rate:.0%} duel win rate "
            f"({duels.success}/{duels.total})"
        ),
        "-" * width,
        " PIPELINE VERIFIED — events → collector → POST /players → GET profile",
        "=" * width,
    ]
    return "\n".join(lines)


def run_simulation(
    client: httpx.Client,
    base_url: str,
    *,
    delay_seconds: float = 0.0,
    log: Any = sys.stdout,
    sequence: Sequence[SecondScript] | None = None,
) -> SimulationReport:
    """Ingest the five-second script and GET the consolidated metrics.

    Args:
        client: HTTP client used for POST/GET.
        base_url: FastAPI origin.
        delay_seconds: Optional pause after each match-second (``1.0`` for a
            live 5-second wall-clock run).
        log: File-like object for progress lines.
        sequence: Override script; defaults to :func:`build_attacking_sequence`.

    Returns:
        GET-verified playmaker and striker profiles plus a summary string.
    """

    ensure_api_running(client, base_url)
    frames = list(sequence or build_attacking_sequence())
    playmaker, striker = kickoff_collectors()
    collectors = (playmaker, striker)

    print("Setup: posting kick-off profiles for Playmaker (CAM) and Striker (ST).", file=log)
    for collector in collectors:
        post_profile(client, base_url, collector)

    for frame in frames:
        print(f"  t={frame.second}s  {frame.description}", file=log)
        for collector in collectors:
            collector.apply(frame.event)
            post_profile(client, base_url, collector)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    print("Verification: GET consolidated profiles.", file=log)
    playmaker_profile = get_profile(client, base_url, PLAYMAKER_ID)
    striker_profile = get_profile(client, base_url, STRIKER_ID)
    summary = verify_consolidated_metrics(playmaker_profile, striker_profile)
    print(summary, file=log)
    return SimulationReport(
        playmaker=playmaker_profile,
        striker=striker_profile,
        summary=summary,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI flags for the standalone simulator."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"FastAPI origin (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait after each match-second (default: 1.0 for a live 5s run).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""

    args = parse_args(argv)
    try:
        with httpx.Client() as client:
            run_simulation(client, args.base_url, delay_seconds=max(args.delay, 0.0))
    except SimulatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
