"""Pluggable taggers: a clip in, raw events (clip-relative times) out.

Backends:

* ``VisionLLMTagger`` - OpenAI-compatible ``/chat/completions`` (OpenRouter).
  Configured by ``TAGGER_API_URL``, ``TAGGER_API_KEY``, ``TAGGER_MODEL``.
  ``TAGGER_INPUT`` = ``video`` (default: the whole clip as a base64 mp4
  ``video_url`` part, re-encoded to ``TAGGER_VIDEO_HEIGHT`` (480) /
  ``TAGGER_VIDEO_BITRATE`` (500k) / ``TAGGER_VIDEO_FPS`` (10); needs a
  video-capable model such as google/gemini-2.5-flash) or ``frames`` (legacy:
  ``TAGGER_FRAMES`` evenly spaced JPEGs at ``TAGGER_FRAME_WIDTH``).
  ``TAGGER_PROMPT`` = analyst (default: analyst event codes with start/end
  coordinates, like hand tagging) | base | v2 (legacy taxonomy prompts).
  Also ``TAGGER_RESPONSE_FORMAT``, ``TAGGER_TIMEOUT``. json_schema with a
  json_object retry when the model collapses to an empty answer.
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

from statman.autotag.clips import Clip, encode_for_model, extract_frames
from statman.autotag.taxonomy import (
    CODES, EVENT_TYPES, FREE_KICK_MAX_DISTANCE_M, TAXONOMY, clock_to_seconds, code_json_schema, from_code_event,
    json_schema,
)

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


def _system_prompt(variant: str = "base") -> str:
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
    if variant == "v2":
        lines += _PROMPT_V2
    lines.append('Each event object MUST use the key "type", e.g. {"type":"shot","team":"home","t_clip_seconds":3.5,...}.')
    return "\n".join(lines)


_PROMPT_V2 = [
    "CAMERA: usually a single wide elevated sideline camera; players are small and the ball is tiny.",
    "Track the ball and which team is in possession frame by frame before listing events.",
    "Set pieces: a corner is taken from the corner arc with players crowded in the box; a free kick is a dead-ball restart with a wall or players lined up.",
    "goal = ball in the net followed by celebration, players walking back, or a centre-spot restart. Use the score bug (if visible) to confirm goals.",
    "Never invent evenly spaced events (one per frame). Tag an event only when you can see it happen.",
]

ANALYST_PROMPT = [
    "You are a professional football (soccer) performance analyst hand-tagging match video, event by event.",
    "You receive one continuous clip of match video (usually a wide elevated sideline camera; players are small).",
    "Watch the whole clip and log EVERY on-ball event in order. Never summarise, never group several passes into one.",
    "Codes: PASS, CROSS, SHOT, SAVE, TACKLE, INTERCEPT, AERIAL, DUEL, FOUL, CARD, CORNER, FK, THROW, GOALKICK, "
    "GK_PASS, CLEAR, RECOVERY, LOST, GAP.",
    "clock = the match clock (mm:ss) when the event happens: clip start clock + seconds into the clip.",
    "team = home or away (use the team names and kit colours given). player / shirt only if you can actually read "
    "them (or match a readable number to the lineup); otherwise null. Never guess names.",
    "outcome: PASS/CROSS/GK_PASS/THROW/GOALKICK/TACKLE/AERIAL/DUEL = success|fail; SHOT = on|off|blocked|goal|post; "
    "CARD = yellow|red; otherwise null.",
    "A misplaced pass (intercepted, out of play, to nobody) is outcome fail - always.",
    "A goalkeeper catching or claiming a cross is RECOVERY (team = goalkeeper's team), not SAVE. SAVE only stops a SHOT.",
    "RECOVERY = winning a loose ball; LOST = losing the ball by miscontrol or being dispossessed (not a misplaced pass);"
    " INTERCEPT = cutting out an opponent pass; CLEAR = defensive clearance without a target.",
    "AERIAL and DUEL: log one event per player involved (both teams), success for the winner, fail for the loser.",
    "Coordinates are 0-100 and always from the ACTING team's view: x=100 is the goal that team attacks, x=0 its own "
    "goal; y=0 its right touchline, y=100 its left touchline. Use the attacking direction given for this half to "
    "convert what you see on screen. x1,y1 = where the action starts; x2,y2 = where it ends (pass/cross/shot/clear "
    "destination, or same as start for on-the-spot actions). null if you truly cannot place it.",
    "When the camera is off the ball (replay, close-up, crowd, broadcast graphic) write ONE GAP event (team = the "
    "team last in possession, coordinates null, detail = what is shown) instead of inventing events.",
    "The clip overlaps the previous one by a few seconds: do not log an event twice; an event cut off at the very "
    "start of the clip that you cannot see fully may be skipped.",
    "detail = a few words (e.g. 'long ball to the left winger', 'header wide'). confidence 0-1.",
    'Return ONLY JSON: {"events": [{"clock":"12:34","team":"home","code":"PASS","player":null,"shirt":8,'
    '"outcome":"success","x1":40,"y1":30,"x2":55,"y2":20,"detail":"...","confidence":0.8}, ...]}.',
]


def analyst_prompt() -> str:
    return "\n".join(ANALYST_PROMPT)


def _fmt_clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def clip_context_text(clip: Clip, context: dict[str, Any]) -> str:
    """Match context for one clip: teams, kits, lineups, attacking direction, clip start clock."""

    teams = context.get("teams") or {}
    kits = context.get("kits") or {}
    kit_text = kits if isinstance(kits, str) else ""
    if not isinstance(kits, dict):
        kits = {}
    lines = [
        f"Clip {clip.index}: {clip.duration:.0f} s of video, half {clip.period}. "
        f"Match clock at clip start = {_fmt_clock(clip.match_start)}; at clip end = "
        f"{_fmt_clock(clip.match_start + clip.duration)}.",
        f"home = {teams.get('home') or 'home team'}" + (f" (kit: {kits['home']})" if kits.get("home") else "")
        + f"; away = {teams.get('away') or 'away team'}" + (f" (kit: {kits['away']})" if kits.get("away") else "") + ".",
    ]
    if kit_text:
        lines.append(f"Kits: {kit_text}.")
    attacks = context.get("home_attacks")  # 'left'|'right' on screen for this clip's half
    if attacks:
        other = "left" if str(attacks).lower() == "right" else "right"
        lines.append(
            f"In this half home attacks the goal on the {str(attacks).upper()} of the screen and away attacks the "
            f"{other.upper()} goal."
        )
    else:
        lines.append("Attacking direction not given: work it out from the goalkeepers' positions and kick-offs.")
    for side in ("home", "away"):
        players = (context.get("lineups") or {}).get(side) or []
        if players:
            roster = ", ".join(
                f"{p.get('shirt')} {p.get('name') or ''}".strip() for p in players if p.get("shirt") is not None
            )
            lines.append(f"{side} shirt numbers: {roster}.")
    if context.get("corrective"):
        lines.append(str(context["corrective"]))
    return "\n".join(lines)


_TYPE_ALIASES = ("event_type", "event", "kind", "action")
_COLLAPSE_COMPLETION_TOKENS = 10


def normalize_event(e: dict[str, Any]) -> dict[str, Any]:
    """Map common key/value drift (event_type, 'Free Kick') onto the schema."""

    e = dict(e)
    if "type" not in e:
        for k in _TYPE_ALIASES:
            if k in e:
                e["type"] = e.pop(k)
                break
    if isinstance(e.get("type"), str):
        e["type"] = e["type"].strip().lower().replace(" ", "_").replace("-", "_")
    for k in ("t_clip_seconds", "t", "time"):
        if k in e and k != "t_clip_seconds" and "t_clip_seconds" not in e:
            e["t_clip_seconds"] = e.pop(k)
    return e


def suppress_repetition(events: list[dict[str, Any]], frame_times: list[float], *, slack: float = 0.3) -> list[dict[str, Any]]:
    """Drop runs where the model emits the same non-pass event on (nearly) every frame.

    Benchmarks showed e.g. 13 'shot'+'save' pairs, one per frame, in a corner
    clip. A real shot/save/corner/goal does not repeat within ~2 s, so keep the
    first of each same-type, same-team cluster closer than 2 s.
    """

    out: list[dict[str, Any]] = []
    last: dict[tuple[Any, Any], float] = {}
    for e in sorted(events, key=lambda x: float(x.get("t_clip_seconds") or 0)):
        t = float(e.get("t_clip_seconds") or 0)
        key = (e.get("type"), e.get("team"))
        if e.get("type") not in {"pass", "aerial_duel", "goal_conceded"} and key in last and t - last[key] < 2.0:
            continue
        last[key] = t
        out.append(e)
    passes = [e for e in out if e.get("type") == "pass"]
    if frame_times and len(passes) >= max(4, int(0.8 * len(frame_times))):
        on_frames = sum(
            1 for e in passes if any(abs(float(e.get("t_clip_seconds") or -9) - ft) <= slack for ft in frame_times)
        )
        if on_frames >= 0.8 * len(passes):
            for e in passes:  # one pass per frame = fabricated; keep but flag for review
                e["confidence"] = min(float(e.get("confidence") or 0.2), 0.2)
                e["suspect"] = "one_per_frame"
    return out


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
        frame_width: int | None = None,
        prompt: str | None = None,
        input_mode: str | None = None,
        video_height: int | None = None,
        video_bitrate: str | None = None,
        video_fps: float | None = None,
        client: Any = None,
    ) -> None:
        self.api_url = (api_url if api_url is not None else os.environ.get("TAGGER_API_URL", "")).strip()
        self.api_key = (api_key if api_key is not None else os.environ.get("TAGGER_API_KEY", "")).strip()
        self.model = (model if model is not None else os.environ.get("TAGGER_MODEL", "")).strip()
        self.frames = int(frames or os.environ.get("TAGGER_FRAMES") or 10)
        self.frame_width = int(frame_width or os.environ.get("TAGGER_FRAME_WIDTH") or 1280)
        self.prompt = (prompt or os.environ.get("TAGGER_PROMPT") or "analyst").strip().lower()
        mode = (input_mode or os.environ.get("TAGGER_INPUT") or "video").strip().lower()
        self.input_mode = mode if mode in {"video", "frames"} else "video"
        self.video_height = int(video_height or os.environ.get("TAGGER_VIDEO_HEIGHT") or 480)
        self.video_bitrate = (video_bitrate or os.environ.get("TAGGER_VIDEO_BITRATE") or "500k").strip()
        self.video_fps = float(video_fps or os.environ.get("TAGGER_VIDEO_FPS") or 10)
        self.total_cost = 0.0
        self.usage_total: dict[str, Any] = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                            "total_tokens": 0, "cost_usd": 0.0}
        self.last_usage: dict[str, Any] = {}
        self.response_format = (response_format or os.environ.get("TAGGER_RESPONSE_FORMAT") or "json_schema").strip()
        self.timeout = float(timeout or os.environ.get("TAGGER_TIMEOUT") or 120)
        self._client = client

    def enabled(self) -> bool:
        return bool(self.api_url and self.model)

    def endpoint(self) -> str:
        url = self.api_url.rstrip("/")
        return url if url.endswith("/chat/completions") else url + "/chat/completions"

    @property
    def analyst(self) -> bool:
        return self.prompt not in {"base", "v2"}

    def _response_format(self, response_format: str) -> dict[str, Any] | None:
        if response_format == "json_schema":
            schema = code_json_schema() if self.analyst else json_schema()
            return {"type": "json_schema", "json_schema": {"name": "statman_events", "strict": True, "schema": schema}}
        if response_format == "json_object":
            return {"type": "json_object"}
        return None

    def _body(self, content: list[dict[str, Any]], response_format: str | None) -> dict[str, Any]:
        system = analyst_prompt() if self.analyst else _system_prompt(self.prompt)
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "usage": {"include": True},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        rf = self._response_format(response_format or self.response_format)
        if rf:
            body["response_format"] = rf
        return body

    def _intro(self, clip: Clip, context: dict[str, Any]) -> str:
        if self.analyst:
            return clip_context_text(clip, context)
        teams = context.get("teams") or {}
        intro = (
            f"Clip {clip.index}: {clip.duration:.1f} s, match clock {clip.match_start:.0f} s at clip start. "
            f"home = {teams.get('home') or 'home team'}; away = {teams.get('away') or 'away team'}. "
            f"Report t_clip_seconds between 0 and {clip.duration:.1f}."
        )
        if context.get("kits"):
            intro += f" Kits: {context['kits']}."
        attacks = context.get("home_attacks")
        if attacks:
            intro += f" home attacks the goal on the {str(attacks).upper()} of the image; away attacks the other goal."
        if context.get("corrective"):
            intro += "\n" + str(context["corrective"])
        return intro

    def build_request(
        self, frames: list[tuple[float, bytes]], context: dict[str, Any], clip: Clip, *, response_format: str | None = None
    ) -> dict[str, Any]:
        """Frames mode: evenly spaced JPEG frames as image_url parts."""

        content: list[dict[str, Any]] = [{"type": "text", "text": self._intro(clip, context)}]
        for t, jpeg in frames:
            content.append({"type": "text", "text": f"frame t={t:.2f}s"})
            content.append({
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")},
            })
        return self._body(content, response_format)

    def build_video_request(
        self, video: bytes, context: dict[str, Any], clip: Clip, *, response_format: str | None = None,
        mime: str = "video/mp4",
    ) -> dict[str, Any]:
        """Video mode: the whole clip as one base64 data URL ``video_url`` part (OpenRouter format)."""

        content: list[dict[str, Any]] = [
            {"type": "text", "text": self._intro(clip, context)},
            {"type": "video_url", "video_url": {"url": f"data:{mime};base64," + base64.b64encode(video).decode("ascii")}},
            {"type": "text", "text": "Tag every on-ball event in this clip now."},
        ]
        return self._body(content, response_format)

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
            if not isinstance(e, dict):
                continue
            if "code" in e or str(e.get("type") or "").strip().upper() in CODES and "clock" in e:
                conv = from_code_event(e)
                if conv is None:
                    continue
                raw_clock = conv.pop("clock", None)
                t_clip = clock_to_clip_seconds(raw_clock, clip)
                if clock_outside_clip(raw_clock, clip):
                    conv["clock_outside"] = True
                if t_clip is None and conv.get("t_clip_seconds") is None:
                    continue
                if t_clip is not None:
                    conv["t_clip_seconds"] = t_clip
                out.append(conv)
                continue
            e = normalize_event(e)
            if e.get("type") in EVENT_TYPES:
                out.append(e)
        return out

    def _requests(self, clip: Clip, context: dict[str, Any]):
        """(build(response_format) -> body, frame_times) for the configured input mode."""

        if self.input_mode == "video":
            video = encode_for_model(
                Path(clip.path), height=self.video_height, bitrate=self.video_bitrate, fps=self.video_fps
            )
            log.info("tagger clip %s: sending %.1f MB video", clip.index, len(video) / 1e6)
            return (lambda rf=None: self.build_video_request(video, context, clip, response_format=rf)), []
        frames = extract_frames(Path(clip.path), self.frames, clip.duration, width=self.frame_width)
        return (lambda rf=None: self.build_request(frames, context, clip, response_format=rf)), [t for t, _ in frames]

    def tag_clip(self, clip: Clip, context: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.enabled():
            raise TaggerUnavailable("Vision tagger disabled: set TAGGER_API_URL and TAGGER_MODEL")
        if not clip.path:
            raise ValueError(f"clip {clip.index} has no file")
        build, frame_times = self._requests(clip, context)
        body = build()
        last: Exception | None = None
        self.last_usage = {}
        for attempt in range(3):
            try:
                payload = self._post(body)
                self._account(payload, clip)
                events = self.parse_response(payload, clip)
                if not events and self.is_collapsed(payload) and self.response_format == "json_schema":
                    # Strict schema often makes the model bail out with {"events":[]} in ~5 tokens.
                    log.info("tagger clip %s: empty-output collapse, retrying with json_object", clip.index)
                    retry = self._post(build("json_object"))
                    self._account(retry, clip)
                    events = self.parse_response(retry, clip)
                if self.input_mode == "frames":
                    return suppress_repetition(events, frame_times)
                return events
            except Exception as exc:  # noqa: BLE001 - retry transport and parse errors
                last = exc
                log.warning("tagger clip %s attempt %s failed: %s", clip.index, attempt + 1, exc)
                time.sleep(min(8, 2 ** attempt))
        raise RuntimeError(f"tagger failed on clip {clip.index}: {last}")


def clock_to_clip_seconds(clock: Any, clip: Clip) -> float | None:
    """Model match clock -> seconds into the clip (clamped to the clip)."""

    secs = clock_to_seconds(clock)
    if secs is None:
        return None
    rel = secs - clip.match_start
    if -5.0 <= rel <= clip.duration + 5.0:
        return round(min(max(rel, 0.0), clip.duration), 2)
    if 0.0 <= secs <= clip.duration:  # model reported time into the clip instead of the match clock
        return round(secs, 2)
    return round(min(max(rel, 0.0), clip.duration), 2)


def clock_outside_clip(clock: Any, clip: Clip, slack: float = 5.0) -> bool:
    """True when a model clock is neither inside the clip window nor plain seconds-into-clip."""

    secs = clock_to_seconds(clock)
    if secs is None:
        return False
    rel = secs - clip.match_start
    return not (-slack <= rel <= clip.duration + slack) and not (0.0 <= secs <= clip.duration)


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    u = payload.get("usage") if isinstance(payload, dict) else None
    return u if isinstance(u, dict) else {}


def _is_collapsed(payload: dict[str, Any]) -> bool:
    tokens = _usage(payload).get("completion_tokens")
    return tokens is not None and int(tokens) < _COLLAPSE_COMPLETION_TOKENS


def _account(self: VisionLLMTagger, payload: dict[str, Any], clip: Clip) -> None:
    """Add one response's token usage / cost (OpenRouter ``usage``) to the running totals."""

    u = _usage(payload)
    if not u:
        return
    tot = self.usage_total
    tot["calls"] += 1
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            n = int(u.get(key) or 0)
        except (TypeError, ValueError):
            n = 0
        tot[key] += n
        self.last_usage[key] = self.last_usage.get(key, 0) + n
    cost = u.get("cost")
    if cost is not None:
        self.total_cost += float(cost)
        tot["cost_usd"] = round(self.total_cost, 6)
        self.last_usage["cost_usd"] = round(self.last_usage.get("cost_usd", 0.0) + float(cost), 6)
    log.info(
        "tagger clip %s usage prompt=%s completion=%s cost=$%.4f (running $%.4f, %s tokens)",
        clip.index, u.get("prompt_tokens"), u.get("completion_tokens"), float(cost or 0), self.total_cost,
        tot["total_tokens"],
    )


VisionLLMTagger.is_collapsed = staticmethod(_is_collapsed)  # type: ignore[attr-defined]
VisionLLMTagger._account = _account  # type: ignore[attr-defined]


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
            "input": llm.input_mode,
            "video_height": llm.video_height,
            "video_bitrate": llm.video_bitrate,
            "video_fps": llm.video_fps,
            "frames_per_clip": llm.frames,
            "response_format": llm.response_format,
            "frame_width": llm.frame_width,
            "prompt": llm.prompt,
        },
    }
