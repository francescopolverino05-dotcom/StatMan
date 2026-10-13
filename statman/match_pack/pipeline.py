"""Create and update match packs; compute fact-sourced sheets."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, BinaryIO

from statman.match_pack import store
from statman.match_pack.facts import EXAMPLE_FACTS, normalize_facts, parse_facts_text
from statman.match_pack.formation import extract_pdf_text
from statman.match_pack.sheet_from_facts import sheet_from_facts
from statman.video.pipeline import DEFAULT_MAX_UPLOAD_BYTES

# Align with full-match guidance: 720p ~1–2 GB; hard cap matches video path.
DEFAULT_MAX_VIDEO_BYTES = DEFAULT_MAX_UPLOAD_BYTES


def create_pack(
    *,
    title: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any]:
    pack_id = store.new_pack_id()
    meta: dict[str, Any] = {
        "pack_id": pack_id,
        "status": "draft",
        "title": title or "Untitled match pack",
        "created_at": time.time(),
        "updated_at": time.time(),
        "facts": None,
        "facts_path": None,
        "formation": {"home": None, "away": None},
        "video": None,
        "sheet": None,
        "error": None,
        "phase": "match-pack-phase1",
        "hints": {
            "video": "720p H.264 MP4, roughly 1–2 GB for a 90′ match (max 4 GB).",
            "facts": "JSON with home/away lineups, formation, events (goals/cards/subs), optional set-piece totals.",
            "formation_pdf": "Optional PDF per side; stored + text-extracted in Phase 1.",
        },
    }
    if home_team or away_team:
        meta["facts"] = normalize_facts(
            {
                "home": {"team_name": home_team or "Home"},
                "away": {"team_name": away_team or "Away"},
                "events": [],
            }
        )
    store.write_meta(pack_id, meta)
    return meta


def get_pack(pack_id: str) -> dict[str, Any] | None:
    return store.read_meta(pack_id)


def list_packs(limit: int = 20) -> list[dict[str, Any]]:
    return store.list_meta(limit=limit)


def put_facts(pack_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    facts = normalize_facts(payload)
    return _store_facts(pack_id, meta, facts)


def put_facts_file(pack_id: str, fileobj: BinaryIO, filename: str = "facts.json") -> dict[str, Any]:
    """Accept an uploaded .json facts file without dropping the pack on bad input."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    raw = fileobj.read()
    if not raw:
        raise ValueError("Facts file is empty")
    # Persist the original upload for audit, even before parse succeeds.
    safe = Path(filename).name or "facts_upload.json"
    if not safe.lower().endswith(".json"):
        safe = f"{safe}.json"
    upload_path = store.pack_dir(pack_id) / f"upload_{safe}"
    upload_path.write_bytes(raw if isinstance(raw, bytes) else str(raw).encode("utf-8"))
    try:
        facts = parse_facts_text(raw)
    except ValueError as exc:
        meta["error"] = str(exc)
        meta["facts_upload_path"] = str(upload_path)
        # Keep prior facts intact — do not wipe a good pack on a bad file.
        store.write_meta(pack_id, meta)
        raise
    meta["facts_upload_path"] = str(upload_path)
    meta["error"] = None
    return _store_facts(pack_id, meta, facts)


def _store_facts(pack_id: str, meta: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    facts_path = store.pack_dir(pack_id) / "facts.json"
    facts_path.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    meta["facts"] = facts
    meta["facts_path"] = str(facts_path)
    meta["status"] = "facts_ready" if not meta.get("sheet") else meta.get("status")
    meta["title"] = f"{facts['home']['team_name']} vs {facts['away']['team_name']}"
    meta["error"] = None
    store.write_meta(pack_id, meta)
    return meta


def save_formation_pdf(
    pack_id: str,
    side: str,
    fileobj: BinaryIO,
    filename: str,
) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    side = side.lower().strip()
    if side not in {"home", "away"}:
        raise ValueError("side must be 'home' or 'away'")
    safe = Path(filename).name or f"{side}_formation.pdf"
    if not safe.lower().endswith(".pdf"):
        safe = f"{safe}.pdf"
    dest = store.pack_dir(pack_id) / f"formation_{side}_{safe}"
    with dest.open("wb") as out:
        shutil.copyfileobj(fileobj, out)
    extracted = extract_pdf_text(dest)
    entry = {
        "side": side,
        "filename": safe,
        "path": str(dest),
        "size_bytes": dest.stat().st_size,
        "extract": extracted,
    }
    formation = meta.get("formation") or {"home": None, "away": None}
    formation[side] = entry
    meta["formation"] = formation
    # If facts exist and formation string empty, try a naive fill from PDF text first line.
    facts = meta.get("facts")
    if facts and not facts.get(side, {}).get("formation"):
        text = (extracted.get("text") or "").strip()
        guess = _guess_formation(text)
        if guess:
            facts[side]["formation"] = guess
            meta["facts"] = facts
            facts_path = store.pack_dir(pack_id) / "facts.json"
            facts_path.write_text(json.dumps(facts, indent=2), encoding="utf-8")
            entry["formation_guess"] = guess
    store.write_meta(pack_id, meta)
    return meta


def attach_formation(pack_id: str, side: str, fileobj: BinaryIO, filename: str) -> dict[str, Any]:
    return save_formation_pdf(pack_id, side, fileobj, filename)


def _guess_formation(text: str) -> str | None:
    import re

    m = re.search(r"\b(\d-\d-\d(?:-\d)?)\b", text)
    return m.group(1) if m else None


def attach_video_bytes(
    pack_id: str,
    fileobj: BinaryIO,
    filename: str,
    *,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
) -> dict[str, Any]:
    """One-shot video attach for smaller files / tests. Prefer chunked UI upload."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    safe = Path(filename).name or "match.mp4"
    dest = store.pack_dir(pack_id) / f"video_{safe}"
    written = 0
    with dest.open("wb") as out:
        while True:
            chunk = fileobj.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                dest.unlink(missing_ok=True)
                raise ValueError(
                    f"Video exceeds max size ({max_bytes // (1024**3)} GB). "
                    "Use 720p H.264 (~1–2 GB)."
                )
            out.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise ValueError("Empty video upload")
    meta["video"] = {
        "filename": safe,
        "path": str(dest),
        "size_bytes": written,
        "status": "ready",
        "hint": "720p / 1–2 GB recommended",
    }
    store.write_meta(pack_id, meta)
    return meta


def link_video_job(pack_id: str, video_job_id: str, *, video_path: str | None = None) -> dict[str, Any]:
    """Attach an existing ``/api/video`` job to this pack."""
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    meta["video"] = {
        "video_job_id": video_job_id,
        "path": video_path,
        "status": "linked",
    }
    store.write_meta(pack_id, meta)
    return meta


def init_pack_video(
    pack_id: str,
    filename: str,
    size_bytes: int,
    *,
    max_bytes: int = DEFAULT_MAX_VIDEO_BYTES,
    chunk_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    if size_bytes <= 0:
        raise ValueError("size_bytes must be > 0")
    if size_bytes > max_bytes:
        raise ValueError(
            f"Video exceeds max size ({max_bytes // (1024**3)} GB). Compress to 720p (~1–2 GB)."
        )
    safe = Path(filename).name or "match.mp4"
    dest = store.pack_dir(pack_id) / f"video_{safe}"
    dest.write_bytes(b"")
    meta["video"] = {
        "filename": safe,
        "path": str(dest),
        "size_bytes": int(size_bytes),
        "bytes_received": 0,
        "chunk_bytes": int(chunk_bytes),
        "status": "uploading",
    }
    meta["status"] = "uploading_video"
    store.write_meta(pack_id, meta)
    return meta


def append_pack_video_chunk(pack_id: str, data: bytes, *, offset: int) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    if video.get("status") not in {"uploading", "ready"}:
        raise ValueError("Pack is not accepting video chunks")
    expected = int(video.get("bytes_received") or 0)
    if int(offset) != expected:
        raise ValueError(f"Chunk offset mismatch: expected {expected}, got {offset}")
    if not data:
        raise ValueError("Empty chunk")
    size_bytes = int(video.get("size_bytes") or 0)
    if expected + len(data) > size_bytes:
        raise ValueError("Chunk would exceed declared size")
    dest = Path(video["path"])
    with dest.open("ab") as out:
        out.write(data)
    received = expected + len(data)
    video["bytes_received"] = received
    video["upload_pct"] = int(100 * received / size_bytes) if size_bytes else 0
    video["status"] = "uploading"
    meta["video"] = video
    store.write_meta(pack_id, meta)
    return meta


def finish_pack_video(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    video = meta.get("video") or {}
    dest = Path(video.get("path") or "")
    actual = dest.stat().st_size if dest.exists() else 0
    expected = int(video.get("size_bytes") or 0)
    if actual == 0:
        raise ValueError("Video file is empty")
    if expected and actual != expected:
        raise ValueError(f"Upload incomplete: received {actual} of {expected} bytes")
    video["bytes_received"] = actual
    video["size_bytes"] = actual
    video["status"] = "ready"
    video["upload_pct"] = 100
    meta["video"] = video
    meta["status"] = "video_ready" if meta.get("facts") else "draft"
    store.write_meta(pack_id, meta)
    return meta


def compute_pack(pack_id: str) -> dict[str, Any]:
    meta = store.read_meta(pack_id)
    if meta is None:
        raise FileNotFoundError(f"Unknown pack_id={pack_id}")
    facts = meta.get("facts")
    if not facts:
        raise ValueError("Upload match facts JSON before computing the sheet")
    sheet = sheet_from_facts(facts, pack_id=pack_id)
    # Re-attach Phase-2 film tags when present so recompute does not drop them.
    film_path = store.pack_dir(pack_id) / "film_stats.json"
    if film_path.exists():
        from statman.match_pack.film_merge import merge_film_into_sheet

        film_stats = json.loads(film_path.read_text(encoding="utf-8"))
        sheet = merge_film_into_sheet(sheet, film_stats, pack_id=pack_id)
        meta["status"] = "phase2_ready"
        meta["phase"] = "match-pack-phase2"
    else:
        meta["status"] = "sheet_ready"
    sheet_path = store.pack_dir(pack_id) / "sheet.json"
    sheet_path.write_text(json.dumps(sheet, indent=2, default=str), encoding="utf-8")
    meta["sheet"] = sheet
    meta["sheet_path"] = str(sheet_path)
    meta["error"] = None
    # Coverage summary at top level for the UI.
    meta["coverage"] = sheet["source"]["coverage"]
    store.write_meta(pack_id, meta)
    return meta


def example_facts() -> dict[str, Any]:
    return EXAMPLE_FACTS
