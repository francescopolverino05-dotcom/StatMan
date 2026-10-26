"""Score candidate moments against hand tags (time recall/precision, chance baseline, team, possession)."""
from __future__ import annotations

import statistics as st
from dataclasses import dataclass


@dataclass
class HandEvent:
    t: float       # match seconds
    team: str      # home / away
    type: str
    outcome: str
    shirt: int | None


def load_hand(path, home_name: str = "Napoli") -> list[HandEvent]:
    """Parse ``MM:SS|Team|TYPE|pos|num|outcome|...`` lines."""
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        c = line.split("|")
        mm, ss = c[0].split(":")
        out.append(HandEvent(int(mm) * 60 + int(ss), "home" if c[1] == home_name else "away", c[2], c[5],
                             int(c[4]) if c[4] else None))
    return sorted(out, key=lambda e: e.t)


def match(hand_t: list[float], cand_t: list[float], window: float) -> list[tuple[int, int]]:
    """Greedy one-to-one: each hand event (in time order) takes the closest unused candidate within window."""
    used, pairs = set(), []
    for i, h in sorted(enumerate(hand_t), key=lambda x: x[1]):
        best = None
        for j, a in enumerate(cand_t):
            if j in used:
                continue
            d = abs(a - h)
            if d <= window and (best is None or d < best[0]):
                best = (d, j)
        if best:
            used.add(best[1]); pairs.append((i, best[1]))
    return pairs


def chance(hand_t, cand_t, window, lo, hi, shifts=range(15, 166, 5)) -> float:
    """Mean matches when the candidate times are circularly shifted inside [lo, hi) (as in cmp2)."""
    span = hi - lo
    return st.mean(len(match(hand_t, [lo + ((a - lo + s) % span) for a in cand_t], window)) for s in shifts)


def possession_changes(hand: list[HandEvent]) -> list[float]:
    return [b.t for a, b in zip(hand, hand[1:]) if b.team != a.team]


def score(hand: list[HandEvent], moments: list[dict], offset: float, lo: float, hi: float) -> dict:
    """``moments``: dicts with ``t`` (clip seconds), ``team``, ``possession_change``. match_t = t + offset."""
    ht = [h.t for h in hand]
    ct = [m["t"] + offset for m in moments]
    res: dict = {"hand_events": len(hand), "candidates": len(moments),
                 "candidates_per_min": round(len(moments) / ((hi - lo) / 60), 1),
                 "hand_per_min": round(len(hand) / ((hi - lo) / 60), 1)}
    for w in (1, 2):
        pr = match(ht, ct, w)
        ch = chance(ht, ct, w, lo, hi)
        res[f"w{w}"] = {"matched": len(pr), "recall": round(len(pr) / len(hand), 3),
                        "precision": round(len(pr) / max(len(moments), 1), 3),
                        "chance_recall": round(ch / len(hand), 3), "chance_precision": round(ch / max(len(moments), 1), 3)}
    pr = match(ht, ct, 2)
    tp = [(hand[i].team, moments[j]["team"]) for i, j in pr]
    known = [(a, b) for a, b in tp if b in ("home", "away")]
    res["team"] = {"pairs": len(tp), "with_team": len(known), "agree": sum(a == b for a, b in known),
                   "accuracy": round(sum(a == b for a, b in known) / max(len(known), 1), 3),
                   "majority_baseline": round(max(sum(a == "home" for a, _ in known), sum(a == "away" for a, _ in known)) / max(len(known), 1), 3)}
    hc = possession_changes(hand)
    fl = [m["t"] + offset for m in moments if m.get("possession_change")]
    pc = {}
    for w in (1, 2, 3):
        p = match(hc, fl, w)
        c = chance(hc, fl, w, lo, hi) if fl else 0
        pc[f"w{w}"] = {"matched": len(p), "recall": round(len(p) / max(len(hc), 1), 3),
                       "precision": round(len(p) / max(len(fl), 1), 3), "chance_matched": round(c, 1)}
    # possession team at hand events: last confirmed team at or before the event
    seq = sorted((m["t"] + offset, m.get("possession_team")) for m in moments if m.get("possession_team"))
    agree = n = 0
    for h in hand:
        cur = None
        for t, tm in seq:
            if t <= h.t + 1:
                cur = tm
            else:
                break
        if cur:
            n += 1; agree += cur == h.team
    pc["hand_changes"] = len(hc); pc["flags"] = len(fl)
    pc["team_in_possession_agree"] = f"{agree}/{n}"
    res["possession"] = pc
    return res
