"""Pluggable taggers: a clip in, raw events (clip-relative times) out.

Backends:

* ``VisionLLMTagger`` - OpenAI-compatible ``/chat/completions`` with sampled
  frames. Configured by ``TAGGER_API_URL``, ``TAGGER_API_KEY``, ``TAGGER_MODEL``
  (optional ``TAGGER_FRAMES``, ``TAGGER_RESPONSE_FORMAT``, ``TAGGER_TIMEOUT``).
  Disabled (``enabled() is False``) when URL or model is unset.
* ``FixtureTagger`` - deterministic, reads a JSON fixture keyed by clip index.
  For tests and offline demos only; select with ``STATMAN_TAGGER=fixture`` and
  ``STATMAN_TAGGER_FIXTURE=/path.json``.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol

from statman.autotag.clips import Clip, extract_frames
from statman.autotag.taxonomy import EVENT_TYPES, FREE_KICK_MAX_DISTANCE_M, TAXONOMY, json_schema

log = logging.getLogger("statman.autotag")


class TaggerUnavailable(RuntimeError):
    """The selected tagger is not configured."""


class Tagger(Protocol):
    name: str

    def enabled(self) -> bool: ...

    def tag_clip(self, clip: Clip, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Return raw events with ``t_clip_seconds`` (0..clip duration)."""
        ...


class FixtureTagger:
    """Replays events from a fixture: {"clips": {"<index>": [event, ...]}}."""

    name = "fixture"

    def __init__(self, fixture: dict[str, Any] | str | Path) -> None:
        if not isinstance(fixture, dict):
            fixture = json.loads(Path(fixture).read_text(encoding="utf-8"))
        self._clips = {str(k): list(v) for k, v in (fixture.get("clips") or {}).items()}

    def enabled(self) -> bool:
        return True

    def tag_clip(self, clip: Clip, context: dict[str, Any]) -> list[dict[str, Any]]:
        return [dict(e) for e in self._clips.get(str(clip.index), [])]


def _system_prompt() -> str:
    lines = [
        "You are a professional football (soccer) performance analyst tagging match video.",
        "You receive evenly spaced frames from one short clip, each labelled with its time in seconds from the clip start.",
        "Return ONLY JSON matching the schema: {\"events\": [...]}. Tag only what is clearly visible; never guess.",
        "If unsure, still tag it but give a low confidence (0-1). Return {\"events\": []} if nothing happens.",
        "team is 'home' or 'away' using the kit description given. shirt is the visible shirt number or null.",
        "x,y are 0-100 from the acting team's view attacking left-to-right (x=100 is the goal they attack); null if unknown.",
        "Event types and attributes (set every other attribute to null):",
    ]
    for etype, spec in TAXONOMY.items():
        attrs = ", ".join(f"{k}: {'|'.join(v) if isinstance(v, tuple) else v}" for k, v in spec.items()) or "none"
        lines.append(f"- {etype}: {attrs}")
    lines += [
        "Rules: pass.completed = reached a team-mate. key_pass = last pass before a team-mate's shot.",
        "progressive = pass that breaks an opponent line; set line_broken to the line broken.",
        "cross = delivery from a wide area into the box. box_entry = pass received inside the opponent box.",
        "shot.on_target is false for blocked or missed shots. xg = your estimate of scoring probability.",
        "inside_box = shot taken inside the penalty area. headed = headed attempt.",
        "foul.team = team that committed the foul. card.color yellow|red.",
        f"free_kick only within {FREE_KICK_MAX_DISTANCE_M:.0f} m of goal: outcome direct_shot or crossed_played.",
        "ball_lost only for miscontrol or dispossessed (not misplaced passes).",
        "aerial_duel: one event per team involved, won true/false, source goal_kick|long_ball.",
        "save / goal_conceded / gk_pass are goalkeeper actions: team is the goalkeeper's team.",
        "gk_pass.length short|long, lane middle|flank. A goal also needs a shot event with outcome goal.",
    ]
    return "\n".join(lines)


def _parse_json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class VisionLLMTagger:
    name = "vision_llm"

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        frames: int | None = None,
        response_format: str | None = None,
        timeout: float | None = None,
        client: Any = None,
    ) -> None:
        self.api_url = (api_url if api_url is not None else os.environ.get("TAGGER_API_URL", "")).strip()
        self.api_key = (api_key if api_key is not None else os.environ.get("TAGGER_API_KEY", "")).strip()
        self.model = (model if model is not None else os.environ.get("TAGGER_MODEL", "")).strip()
        self.frames = int(frames or os.environ.get("TAGGER_FRAMES") or 10)
        self.response_format = (response_format or os.environ.get("TAGGER_RESPONSE_FORMAT") or "json_schema").strip()
        self.timeout = float(timeout or os.environ.get("TAGGER_TIMEOUT") or 120)
        self._client = client

    def enabled(self) -> bool:
        return bool(self.api_url and self.model)

    def endpoint(self) -> str:
        url = self.api_url.rstrip("/")
        return url if url.endswith("/chat/completions") else url + "/chat/completions"

    def build_request(self, frames: list[tuple[float, bytes]], context: dict[str, Any], clip: Clip) -> dict[str, Any]:
        teams = context.get("teams") or {}
        intro = (
            f"Clip {clip.index}: {clip.duration:.1f} s, match clock {clip.match_start:.0f} s at clip start. "
            f"home = {teams.get('home') or 'home team'}; away = {teams.get('away') or 'away team'}. "
            f"Report t_clip_seconds between 0 and {clip.duration:.1f}."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": intro}]
        for t, jpeg in frames:
            content.append({"type": "text", "text": f"frame t={t:.2f}s"})
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")},
            })
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": content},
            ],
        }
        if self.response_format == "json_schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "statman_events", "strict": True, "schema": json_schema()},
            }
        elif self.response_format == "json_object":
            body["response_format"] = {"type": "json_object"}
        return body

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(self.endpoint(), json=body, headers=headers)
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._client is None:
                client.close()

    def parse_response(self, payload: dict[str, Any], clip: Clip) -> list[dict[str, Any]]:
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("tagger response has no message content") from exc
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        data = _parse_json(text or "")
        events = data.get("events") if isinstance(data, dict) else data
        if not isinstance(events, list):
            raise ValueError("tagger response is not an event list")
        out = []
        for e in events:
            if isinstance(e, dict) and e.get("type") in EVENT_TYPES:
                out.append(e)
        return out

    def tag_clip(self, clip: Clip, context: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled():
            raise TaggerUnavailable("Vision tagger disabled: set TAGGER_API_URL and TAGGER_MODEL")
        if not clip.path:
            raise ValueError(f"clip {clip.index} has no file")
        frames = extract_frames(Path(clip.path), self.frames, clip.duration)
        body = self.build_request(frames, context, clip)
        last: Exception | None = None
        for attempt in range(3):
            try:
                return self.parse_response(self._post(body), clip)
            except Exception as exc:  # noqa: BLE001 - retry transport and parse errors
                last = exc
                log.warning("tagger clip %s attempt %s failed: %s", clip.index, attempt + 1, exc)
                time.sleep(min(8, 2 ** attempt))
        raise RuntimeError(f"tagger failed on clip {clip.index}: {last}")


def get_tagger(name: str | None = None) -> Tagger:
    """Pick a backend: explicit name, else ``STATMAN_TAGGER``, else the vision LLM."""

    choice = (name or os.environ.get("STATMAN_TAGGER") or "vision_llm").strip().lower()
    if choice in {"fixture", "stub"}:
        path = os.environ.get("STATMAN_TAGGER_FIXTURE", "").strip()
        if not path:
            raise TaggerUnavailable("STATMAN_TAGGER_FIXTURE is not set for the fixture tagger")
        return FixtureTagger(path)
    return VisionLLMTagger()


def tagger_status() -> dict[str, Any]:
    llm = VisionLLMTagger()
    return {
        "selected": (os.environ.get("STATMAN_TAGGER") or "vision_llm").strip().lower(),
        "vision_llm": {
            "enabled": llm.enabled(),
            "api_url": llm.api_url or None,
            "model": llm.model or None,
            "has_api_key": bool(llm.api_key),
            "frames_per_clip": llm.frames,
            "response_format": llm.response_format,
        },
    }
