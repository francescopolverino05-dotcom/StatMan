"""CLI: python -m statman [game_id] | season build|table|players"""

from __future__ import annotations

import json
import sys

from statman.compute import compute_match_stats
from statman.load import (
    DEFAULT_COMPETITION_ID,
    DEFAULT_GAME_ID,
    DEFAULT_SEASON_ID,
    load_match,
)
from statman.season import build_season, player_leaderboard, tournament_table


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "season":
        return _season_cli(args[1:])

    game_id = int(args[0]) if args else DEFAULT_GAME_ID
    print(f"Loading StatsBomb open match {game_id}…", file=sys.stderr)
    bundle = load_match(game_id)
    stats = compute_match_stats(bundle)
    json.dump(stats, sys.stdout, indent=2)
    print(file=sys.stdout)
    return 0


def _season_cli(args: list[str]) -> int:
    if not args:
        print(
            "Usage: python -m statman season build|table|players "
            "[--limit N] [--force] [--sort xg]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    limit: int | None = None
    force = False
    sort = "xg"
    rest = args[1:]
    i = 0
    while i < len(rest):
        if rest[i] == "--limit" and i + 1 < len(rest):
            limit = int(rest[i + 1])
            i += 2
        elif rest[i] == "--force":
            force = True
            i += 1
        elif rest[i] == "--sort" and i + 1 < len(rest):
            sort = rest[i + 1]
            i += 2
        else:
            print(f"Unknown arg: {rest[i]}", file=sys.stderr)
            return 2

    if cmd == "build":

        def progress(done: int, total: int, game_id: int | None) -> None:
            label = f"game {game_id}" if game_id else "done"
            print(f"[{done}/{total}] {label}", file=sys.stderr)

        meta = build_season(
            DEFAULT_COMPETITION_ID,
            DEFAULT_SEASON_ID,
            limit=limit,
            force=force,
            progress_cb=progress,
        )
        json.dump(meta, sys.stdout, indent=2)
        print(file=sys.stdout)
        return 0

    if cmd == "table":
        data = tournament_table(DEFAULT_COMPETITION_ID, DEFAULT_SEASON_ID)
        json.dump(data, sys.stdout, indent=2)
        print(file=sys.stdout)
        return 0

    if cmd == "players":
        data = player_leaderboard(
            DEFAULT_COMPETITION_ID,
            DEFAULT_SEASON_ID,
            sort=sort,
            limit=limit or 40,
        )
        json.dump(data, sys.stdout, indent=2)
        print(file=sys.stdout)
        return 0

    print(f"Unknown season command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
