"""Store formation PDFs and extract lightweight text for Phase 1."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_pdf_text(path: Path, *, max_chars: int = 8000) -> dict[str, Any]:
    """Best-effort text extract; Phase 1 stores the PDF even if parsing is thin."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {
            "ok": False,
            "error": "pypdf not installed",
            "text": "",
            "pages": 0,
        }
    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) >= max_chars:
                break
        text = "\n".join(parts).strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "…"
        return {
            "ok": True,
            "error": None,
            "text": text,
            "pages": len(reader.pages),
            "char_count": len(text),
        }
    except Exception as exc:  # noqa: BLE001 — surface parse failures to the pack meta
        return {
            "ok": False,
            "error": str(exc),
            "text": "",
            "pages": 0,
        }
