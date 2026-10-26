"""Event + correction storage.

``FileEventRepo`` (default) keeps events.json / corrections.json per match.
``PostgresEventRepo`` (DATABASE_URL set) writes the Phase 1 ``events`` and
``corrections`` tables; the review queue is the ``event_review_queue`` view.

Events crossing this module use one dict shape::

    {id, match_id, type, team, shirt, player, t_match_seconds, video_ts_seconds,
     period, x, y, attributes, confidence, review_status, review_reason,
     issues, clip_ids, source}
"""

from __future__ import annotations

import copy
import json
import os
import time
from typing import Any, Protocol

from statman.autotag import store
from statman.persistence.backend import postgres_enabled

KEEP_ON_RETAG = ("confirmed", "corrected", "rejected")
EDITABLE = ("type", "team", "shirt", "player", "t_match_seconds", "x", "y", "x2", "y2", "outcome", "attributes")


class EventRepo(Protocol):
    def list_events(self, match_id: str) -> list[dict[str, Any]]: ...

    def get_event(self, match_id: str, event_id: int) -> dict[str, Any] | None: ...

    def replace_ai_events(self, match_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def add_event(self, match_id: str, event: dict[str, Any]) -> dict[str, Any]: ...

    def replace_marked_events(self, match_id: str, mark: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def update_event(self, match_id: str, event_id: int, fields: dict[str, Any]) -> dict[str, Any]: ...

    def add_correction(self, match_id: str, correction: dict[str, Any]) -> dict[str, Any]: ...

    def list_corrections(self, match_id: str) -> list[dict[str, Any]]: ...


def _clean(event: dict[str, Any], match_id: str) -> dict[str, Any]:
    return {
        "match_id": match_id,
        "type": event["type"],
        "team": event.get("team"),
        "shirt": event.get("shirt"),
        "player": event.get("player"),
        "t_match_seconds": float(event["t_match_seconds"]),
        "video_ts_seconds": event.get("video_ts_seconds"),
        "period": event.get("period"),
        "x": event.get("x"),
        "y": event.get("y"),
        "x2": event.get("x2"),
        "y2": event.get("y2"),
        "outcome": event.get("outcome"),
        "code": event.get("code"),
        "detail": event.get("detail"),
        "attributes": dict(event.get("attributes") or {}),
        "confidence": event.get("confidence"),
        "review_status": event.get("review_status") or "pending",
        "review_reason": list(event.get("review_reason") or []),
        "issues": list(event.get("issues") or []),
        "clip_ids": list(event.get("clip_ids") or []),
        "source": event.get("source") or "ai",
    }


def _marked(ev: dict[str, Any], mark: str) -> bool:
    return ev.get("source") == "human" and mark in (ev.get("review_reason") or [])


def _mark(ev: dict[str, Any], mark: str) -> dict[str, Any]:
    return {**ev, "source": "human", "review_reason": [mark, *[r for r in ev.get("review_reason") or [] if r != mark]]}


class FileEventRepo:
    name = "files"

    def _load(self, match_id: str) -> dict[str, Any]:
        return store.read_doc(match_id, "events", {"next_id": 1, "events": []})

    def _save(self, match_id: str, doc: dict[str, Any]) -> None:
        store.write_doc(match_id, "events", doc)

    def list_events(self, match_id: str) -> list[dict[str, Any]]:
        with store.LOCK:
            return sorted(self._load(match_id)["events"], key=lambda e: (e["t_match_seconds"], e["id"]))

    def get_event(self, match_id: str, event_id: int) -> dict[str, Any] | None:
        for ev in self.list_events(match_id):
            if ev["id"] == event_id:
                return ev
        return None

    def replace_ai_events(self, match_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with store.LOCK:
            doc = self._load(match_id)
            kept = [e for e in doc["events"] if e.get("source") == "human" or e.get("review_status") in KEEP_ON_RETAG]
            for ev in events:
                row = {**_clean(ev, match_id), "id": doc["next_id"], "updated_at": time.time()}
                doc["next_id"] += 1
                kept.append(row)
            doc["events"] = kept
            self._save(match_id, doc)
            return self.list_events(match_id)

    def replace_marked_events(self, match_id: str, mark: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop every human event whose review_reason contains ``mark`` and insert ``events`` (human, marked).

        Used by the semi-automatic tagger (mark ``semi``); the DB only allows source ai|human.
        """
        with store.LOCK:
            doc = self._load(match_id)
            kept = [e for e in doc["events"] if not _marked(e, mark)]
            for ev in events:
                kept.append({**_clean(_mark(ev, mark), match_id), "id": doc["next_id"], "updated_at": time.time()})
                doc["next_id"] += 1
            doc["events"] = kept
            self._save(match_id, doc)
            return self.list_events(match_id)

    def add_event(self, match_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with store.LOCK:
            doc = self._load(match_id)
            row = {**_clean(event, match_id), "id": doc["next_id"], "updated_at": time.time()}
            doc["next_id"] += 1
            doc["events"].append(row)
            self._save(match_id, doc)
            return row

    def update_event(self, match_id: str, event_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        with store.LOCK:
            doc = self._load(match_id)
            for i, ev in enumerate(doc["events"]):
                if ev["id"] == event_id:
                    doc["events"][i] = {**ev, **copy.deepcopy(fields), "updated_at": time.time()}
                    self._save(match_id, doc)
                    return doc["events"][i]
        raise KeyError(f"event {event_id} not found")

    def add_correction(self, match_id: str, correction: dict[str, Any]) -> dict[str, Any]:
        with store.LOCK:
            rows = store.read_doc(match_id, "corrections", [])
            row = {**correction, "id": len(rows) + 1, "match_id": match_id, "created_at": time.time()}
            rows.append(row)
            store.write_doc(match_id, "corrections", rows)
            return row

    def list_corrections(self, match_id: str) -> list[dict[str, Any]]:
        return store.read_doc(match_id, "corrections", [])


_COLS = (
    "id, match_id, period, clock_ms, video_ts_ms, team, type, x, y, flags, confidence, "
    "review_status, source, shirt_number, player_name, meta, end_x, end_y, outcome"
)


class PostgresEventRepo:
    name = "postgres"

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ["DATABASE_URL"].strip()
        from statman.persistence.backend import get_backend

        get_backend()  # applies migrations (001 + 002)

    def _conn(self):
        import psycopg

        return psycopg.connect(self.url, application_name="statman-autotag")

    @staticmethod
    def _row(r: tuple) -> dict[str, Any]:
        (eid, match_id, period, clock_ms, video_ms, team, etype, x, y, flags, conf,
         status, source, shirt, player, meta, end_x, end_y, outcome) = r
        meta = meta or {}
        return {
            "id": int(eid), "match_id": match_id, "type": etype, "team": team, "shirt": shirt,
            "player": player, "t_match_seconds": (clock_ms or 0) / 1000.0,
            "video_ts_seconds": None if video_ms is None else video_ms / 1000.0, "period": period,
            "x": x, "y": y, "x2": end_x, "y2": end_y, "outcome": outcome, "code": meta.get("code"),
            "detail": meta.get("detail"), "attributes": flags or {}, "confidence": conf, "review_status": status,
            "review_reason": meta.get("review_reason", []), "issues": meta.get("issues", []),
            "clip_ids": meta.get("clip_ids", []), "source": source,
        }

    @staticmethod
    def _params(ev: dict[str, Any]) -> tuple:
        from psycopg.types.json import Jsonb

        attrs = ev["attributes"]
        video = ev.get("video_ts_seconds")
        return (
            ev.get("period"), int(round(ev["t_match_seconds"] * 1000)),
            None if video is None else int(round(video * 1000)), ev.get("team"), ev["type"],
            ev.get("outcome") or attrs.get("outcome"), ev.get("x"), ev.get("y"), ev.get("x2"), ev.get("y2"),
            attrs.get("headed") if isinstance(attrs.get("headed"), bool) else None,
            bool(attrs["line_broken"]) if attrs.get("line_broken") else None,
            Jsonb(attrs), ev.get("confidence"), ev["review_status"], ev["source"],
            ev.get("shirt"), ev.get("player"),
            Jsonb({"clip_ids": ev["clip_ids"], "issues": ev["issues"], "review_reason": ev["review_reason"],
                   "code": ev.get("code"), "detail": ev.get("detail")}),
        )

    _INSERT = (
        "INSERT INTO events (match_id, period, clock_ms, video_ts_ms, team, type, outcome, x, y, end_x, end_y, headed, "
        "line_broken, flags, confidence, review_status, source, shirt_number, player_name, meta) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING " + _COLS
    )

    def _ensure_match(self, conn, match_id: str) -> None:
        conn.execute(
            "INSERT INTO matches (id, source) VALUES (%s, 'autotag') ON CONFLICT (id) DO NOTHING", (match_id,)
        )

    def list_events(self, match_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM events WHERE match_id = %s ORDER BY clock_ms, id", (match_id,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def get_event(self, match_id: str, event_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            r = conn.execute(
                f"SELECT {_COLS} FROM events WHERE match_id = %s AND id = %s", (match_id, event_id)
            ).fetchone()
        return self._row(r) if r else None

    def replace_ai_events(self, match_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._ensure_match(conn, match_id)
            conn.execute(
                "DELETE FROM events WHERE match_id = %s AND source = 'ai' AND review_status IN ('pending', 'auto')",
                (match_id,),
            )
            for ev in events:
                conn.execute(self._INSERT, (match_id, *self._params(_clean(ev, match_id))))
        return self.list_events(match_id)

    def replace_marked_events(self, match_id: str, mark: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self._conn() as conn:
            self._ensure_match(conn, match_id)
            conn.execute("DELETE FROM events WHERE match_id = %s AND source = 'human' "
                         "AND COALESCE(meta->'review_reason', '[]'::jsonb) @> %s::jsonb", (match_id, json.dumps([mark])))
            for ev in events:
                conn.execute(self._INSERT, (match_id, *self._params(_clean(_mark(ev, mark), match_id))))
        return self.list_events(match_id)

    def add_event(self, match_id: str, event: dict[str, Any]) -> dict[str, Any]:
        with self._conn() as conn:
            self._ensure_match(conn, match_id)
            r = conn.execute(self._INSERT, (match_id, *self._params(_clean(event, match_id)))).fetchone()
        return self._row(r)

    def update_event(self, match_id: str, event_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        current = self.get_event(match_id, event_id)
        if current is None:
            raise KeyError(f"event {event_id} not found")
        ev = _clean({**current, **fields}, match_id)
        p = self._params(ev)
        with self._conn() as conn:
            r = conn.execute(
                "UPDATE events SET period=%s, clock_ms=%s, video_ts_ms=%s, team=%s, type=%s, outcome=%s, x=%s, y=%s, "
                "end_x=%s, end_y=%s, "
                "headed=%s, line_broken=%s, flags=%s, confidence=%s, review_status=%s, source=%s, shirt_number=%s, "
                f"player_name=%s, meta=%s, updated_at=now() WHERE match_id=%s AND id=%s RETURNING {_COLS}",
                (*p, match_id, event_id),
            ).fetchone()
        return self._row(r)

    def add_correction(self, match_id: str, correction: dict[str, Any]) -> dict[str, Any]:
        from psycopg.types.json import Jsonb

        with self._conn() as conn:
            r = conn.execute(
                "INSERT INTO corrections (event_id, match_id, reviewer, before, after, note) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, EXTRACT(EPOCH FROM created_at)",
                (correction["event_id"], match_id, correction.get("reviewer"),
                 Jsonb({**correction["before"], "_action": correction["action"]}), Jsonb(correction["after"]),
                 correction.get("note")),
            ).fetchone()
        return {**correction, "id": int(r[0]), "match_id": match_id, "created_at": float(r[1])}

    def list_corrections(self, match_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, event_id, reviewer, before, after, note, EXTRACT(EPOCH FROM created_at) "
                "FROM corrections WHERE match_id = %s ORDER BY created_at, id", (match_id,)
            ).fetchall()
        out = []
        for cid, eid, reviewer, before, after, note, created in rows:
            before = dict(before or {})
            out.append({"id": int(cid), "event_id": int(eid), "match_id": match_id, "reviewer": reviewer,
                        "action": before.pop("_action", None), "before": before, "after": after,
                        "note": note, "created_at": float(created)})
        return out


def get_repo() -> EventRepo:
    return PostgresEventRepo() if postgres_enabled() else FileEventRepo()


__all__ = ["EDITABLE", "EventRepo", "FileEventRepo", "PostgresEventRepo", "get_repo"]
