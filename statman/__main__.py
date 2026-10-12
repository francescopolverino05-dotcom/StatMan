"""CLI: python -m statman [game_id]"""

from __future__ import annotations

import json
import sys

from statman.compute import compute_match_stats
from statman.load import DEFAULT_GAME_ID, load_match


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    game_id = int(args[0]) if args else DEFAULT_GAME_ID
    print(f"Loading StatsBomb open match {game_id}…", file=sys.stderr)
    bundle = load_match(game_id)
    stats = compute_match_stats(bundle)
    json.dump(stats, sys.stdout, indent=2)
    print(file=sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
