"""Video binary location. Binaries never go to Postgres.

``STATMAN_VIDEO_DIR`` set -> uploads live there (mount a Railway volume at
that path). Unset -> historical layout under ``.data/`` (wiped on redeploy).
"""

from __future__ import annotations

import os
from pathlib import Path


def configured_video_dir() -> Path | None:
    raw = os.environ.get("STATMAN_VIDEO_DIR", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
