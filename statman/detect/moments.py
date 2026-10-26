"""Candidate event moments: ball touches and possession changes."""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field

from . import ball as ballmod
from .teams import HOME, AWAY, OTHER, TeamModel


@dataclass
class DetectConfig:
    owner_k: float = 0.8          # ball within owner_k * body height of the feet -> that player has it
    near_k: float = 1.5           # kink touches need a player this close
    kink_deg: float = 35.0        # direction change that counts as a touch
    kink_speed_ratio: float = 2.0  # or speed change by this factor
    min_speed_px_s: float = 40.0
    min_sep_s: float = 0.8        # merge candidates closer than this
    persist: int = 2              # samples before a new team counts as in possession
    min_green: float = 0.25       # skip frames that are not a wide pitch view
    max_gap: float = 1.0          # ball interpolation gap (s)
    ball_method: str = "viterbi"  # "viterbi" | "tracklets"
    pan_weight: float = 0.6
    frame_w: float = 1280.0
    frame_h: float = 720.0


@dataclass
class Moment:
    t: float                         # seconds from video (clip) start
    kind: str                        # "owner_change" | "kink"
    score: float
    ball_xy: tuple[float, float] | None   # image pixels
    ball_norm: tuple[float, float] | None  # image coords scaled 0-100 (rough; no pitch homography)
    player_box: tuple[float, float, float, float] | None
    player_dist: float | None        # ball-feet distance in body heights
    team: str                        # home / away / other / unknown (nearest player's kit)
    possession_team: str | None      # confirmed team in possession after this moment
    possession_change: bool
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def nearest(frame, xy, teams: TeamModel):
    best = None
    for p in frame.persons:
        if p.role == "referee":
            continue
        fx, fy = p.feet
        h = max(p.height, 8.0)
        d = math.hypot(xy[0] - fx, xy[1] - (fy - 0.15 * h)) / h
        tm = OTHER if p.role == "goalkeeper" else teams.assign(p.color)
        if best is None or d < best[0]:
            best = (d, p, tm)
    return best


def _angle(v1, v2) -> float:
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(c))


def detect(frames, teams: TeamModel, cfg: DetectConfig | None = None,
           pan: list[tuple[float, float]] | None = None) -> list[Moment]:
    """Candidate moments from per-frame detections.

    ``pan``: optional camera pan events [(t, strength)] from ``camera.pan_events``;
    each becomes a ``pan`` candidate (ball/player fields filled when known).
    """
    cfg = cfg or DetectConfig()
    frames = [f for f in frames if f.green >= cfg.min_green]
    trk = (ballmod.track_viterbi(frames, max_gap=cfg.max_gap) if cfg.ball_method == "viterbi"
           else ballmod.track(frames, max_gap=cfg.max_gap))
    byt = {f.t: f for f in frames}
    times = [f.t for f in frames if f.t in trk]
    raw: list[Moment] = []

    def mk(t, kind, score, near):
        d, p, tm = near if near else (None, None, "unknown")
        if t in trk:
            x, y, _ = trk[t]
            bxy, bn = (round(x, 1), round(y, 1)), (round(100 * x / cfg.frame_w, 1), round(100 * y / cfg.frame_h, 1))
        else:
            bxy = bn = None
        return Moment(t=t, kind=kind, score=score, ball_xy=bxy, ball_norm=bn,
                      player_box=None if p is None else tuple(round(v, 1) for v in p.box),
                      player_dist=None if d is None else round(d, 2), team=tm,
                      possession_team=None, possession_change=False, sources=[kind])

    # 1) owner changes (nearest player within owner_k, a different player than before)
    prev = None  # (t, feet, team)
    for t in times:
        nb = nearest(byt[t], trk[t][:2], teams)
        if not nb or nb[0] > cfg.owner_k:
            continue
        d, p, tm = nb
        if prev is not None:
            pt, pf, ptm = prev
            moved = math.hypot(p.feet[0] - pf[0], p.feet[1] - pf[1])
            if moved > max(p.height, 15) * 1.0 + 300 * (t - pt) * 0.3 or tm != ptm:
                raw.append(mk(t, "owner_change", 1.0 - min(d, 1.5) / 1.5 + (0.5 if tm != ptm else 0), nb))
        else:
            raw.append(mk(t, "owner_change", 0.5, nb))
        prev = (t, p.feet, tm)

    # 2) kinks in the observed ball path near a player
    obs = [t for t in times if trk[t][2]]
    for a, b, c in zip(obs, obs[1:], obs[2:]):
        if b - a > 0.6 or c - b > 0.6:
            continue
        v1 = ((trk[b][0] - trk[a][0]) / (b - a), (trk[b][1] - trk[a][1]) / (b - a))
        v2 = ((trk[c][0] - trk[b][0]) / (c - b), (trk[c][1] - trk[b][1]) / (c - b))
        s1, s2 = math.hypot(*v1), math.hypot(*v2)
        if max(s1, s2) < cfg.min_speed_px_s:
            continue
        ang = _angle(v1, v2) if min(s1, s2) >= cfg.min_speed_px_s * 0.5 else 0.0
        ratio = (max(s1, s2) + 1) / (min(s1, s2) + 1)
        if ang < cfg.kink_deg and ratio < cfg.kink_speed_ratio:
            continue
        nb = nearest(byt[b], trk[b][:2], teams)
        if not nb or nb[0] > cfg.near_k:
            continue
        raw.append(mk(b, "kink", min(ang / 90, 1.0) * 0.5 + min(ratio / 4, 1.0) * 0.5 + (0.3 if nb[0] < cfg.owner_k else 0), nb))

    # 3) camera pan onsets / stops / reversals (auto-follow camera tracks the ball)
    if pan:
        ft = [f.t for f in frames]
        for pt, strength in pan:
            if not ft:
                break
            k = min(ft, key=lambda x: abs(x - pt))
            if abs(k - pt) > 0.3:
                continue
            nb = nearest(byt[k], trk[k][:2], teams) if k in trk else None
            if nb and nb[0] > cfg.near_k:
                nb = None
            raw.append(mk(k, "pan", cfg.pan_weight * min(strength / 200.0, 1.0) + 0.4, nb))

    # merge close candidates, keep the strongest
    raw.sort(key=lambda m: m.t)
    merged: list[Moment] = []
    for m in raw:
        if merged and m.t - merged[-1].t < cfg.min_sep_s:
            keep = merged[-1]
            if m.score > keep.score:
                m.sources = sorted(set(m.sources + keep.sources)); merged[-1] = m
            else:
                keep.sources = sorted(set(keep.sources + m.sources))
            continue
        merged.append(m)

    # possession: confirmed owning team over time; flag the moment where it flips
    poss, streak_team, streak = None, None, 0
    owner_by_t = {}
    for t in times:
        nb = nearest(byt[t], trk[t][:2], teams)
        owner_by_t[t] = nb[2] if nb and nb[0] <= cfg.owner_k and nb[2] in (HOME, AWAY) else None
    flips = []
    for t in times:
        o = owner_by_t[t]
        if o is None:
            continue
        streak = streak + 1 if o == streak_team else 1
        streak_team = o
        if streak >= cfg.persist and o != poss:
            if poss is not None:
                # the flip happened at the first sample of the streak
                first = [x for x in times if x <= t and owner_by_t[x] == o]
                flips.append((first[-cfg.persist] if len(first) >= cfg.persist else t, o))
            poss = o
    fi = 0
    cur = None
    for m in merged:
        while fi < len(flips) and flips[fi][0] <= m.t + 0.5:
            cur = flips[fi][1]
            if abs(flips[fi][0] - m.t) <= 0.5:
                m.possession_change = True
            fi += 1
        m.possession_team = cur
    # flips without a nearby moment become moments of their own
    have = [m.t for m in merged]
    for ft, team in flips:
        if not any(abs(ft - t) <= 0.5 for t in have):
            mm = mk(ft, "possession_flip", 0.6, nearest(byt[ft], trk[ft][:2], teams))
            mm.possession_change, mm.possession_team = True, team
            merged.append(mm)
    merged.sort(key=lambda m: m.t)
    return merged
