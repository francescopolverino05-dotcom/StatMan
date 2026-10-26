"""Ball track from noisy per-frame ball candidates.

Candidates are linked into tracklets (distance gate scaled by elapsed time);
static tracklets (spare balls, line marks) and short low-confidence ones are
dropped; the best non-overlapping tracklets form the track, and gaps up to
``max_gap`` seconds are linearly interpolated.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tracklet:
    pts: list[tuple[float, float, float, float]] = field(default_factory=list)  # (t, x, y, conf)

    @property
    def t0(self) -> float:
        return self.pts[0][0]

    @property
    def t1(self) -> float:
        return self.pts[-1][0]

    def score(self) -> float:
        return sum(p[3] for p in self.pts) + 0.05 * len(self.pts)

    def travel(self) -> float:
        xs = [p[1] for p in self.pts]; ys = [p[2] for p in self.pts]
        return max(max(xs) - min(xs), max(ys) - min(ys))


def link(frames, speed_px_s: float = 900.0, base_px: float = 25.0, max_miss_s: float = 0.4,
         min_conf: float = 0.02) -> list[Tracklet]:
    live: list[Tracklet] = []
    done: list[Tracklet] = []
    for f in frames:
        cands = sorted((b for b in f.balls if b.conf >= min_conf), key=lambda b: -b.conf)
        used = set()
        # extend the strongest tracklets first
        for tr in sorted(live, key=lambda tr: -tr.score()):
            t, x, y, _ = tr.pts[-1]
            gate = base_px + speed_px_s * (f.t - t)
            best = None
            for i, b in enumerate(cands):
                if i in used:
                    continue
                d = ((b.x - x) ** 2 + (b.y - y) ** 2) ** 0.5
                if d <= gate and (best is None or d < best[0]):
                    best = (d, i)
            if best:
                used.add(best[1]); b = cands[best[1]]
                tr.pts.append((f.t, b.x, b.y, b.conf))
        for i, b in enumerate(cands):
            if i not in used:
                live.append(Tracklet([(f.t, b.x, b.y, b.conf)]))
        keep = []
        for tr in live:
            (done if f.t - tr.t1 > max_miss_s else keep).append(tr)
        live = keep
    return done + live


def select(tracklets: list[Tracklet], min_score: float = 0.25, static_px: float = 6.0,
           static_s: float = 2.0) -> list[Tracklet]:
    good = []
    for tr in tracklets:
        if tr.score() < min_score and not (len(tr.pts) == 1 and tr.pts[0][3] >= 0.2):
            continue
        if tr.t1 - tr.t0 >= static_s and tr.travel() < static_px:
            continue  # parked ball / cone / line artefact
        good.append(tr)
    chosen: list[Tracklet] = []
    for tr in sorted(good, key=lambda tr: -tr.score()):
        if all(tr.t1 < c.t0 or tr.t0 > c.t1 for c in chosen):
            chosen.append(tr)
    return sorted(chosen, key=lambda tr: tr.t0)


def track(frames, max_gap: float = 1.0, **kw) -> dict[float, tuple[float, float, bool]]:
    """Return {frame_time: (x, y, observed)} for frames where the ball position is known."""
    sel = select(link(frames, **kw))
    obs: dict[float, tuple[float, float]] = {}
    for tr in sel:
        for t, x, y, _ in tr.pts:
            obs[t] = (x, y)
    times = [f.t for f in frames]
    out: dict[float, tuple[float, float, bool]] = {t: (*obs[t], True) for t in obs}
    ot = sorted(obs)
    for a, b in zip(ot, ot[1:]):
        if 0 < b - a <= max_gap:
            for t in times:
                if a < t < b:
                    w = (t - a) / (b - a)
                    out[t] = (obs[a][0] + w * (obs[b][0] - obs[a][0]), obs[a][1] + w * (obs[b][1] - obs[a][1]), False)
    return out


def _near_player(frame, x: float, y: float) -> float:
    """Distance from (x, y) to the closest non-referee player's feet, in body heights (inf if none)."""
    best = float("inf")
    for p in frame.persons:
        if getattr(p, "role", "person") == "referee":
            continue
        fx, fy = p.feet
        h = max(p.height, 8.0)
        best = min(best, ((x - fx) ** 2 + (y - fy) ** 2) ** 0.5 / h)
    return best


def track_viterbi(frames, speed_px_s: float = 900.0, base_px: float = 25.0, min_conf: float = 0.02,
                  near_bonus: float = 1.0, far_penalty: float = 0.7, miss_cost: float = 0.6,
                  max_gap: float = 1.0) -> dict[float, tuple[float, float, bool]]:
    """Most consistent ball path: per-frame choice between the candidates and "not visible".

    Emission favours confident candidates close to a player's feet (the ball in
    play is almost always near someone); transitions favour short jumps.
    Returns {t: (x, y, observed)} with short gaps interpolated, like ``track``.
    """
    import math
    states_prev: list[tuple[float, float, float] | None] = [None]  # (x, y, conf) or None = MISS
    score_prev = [0.0]
    back: list[list[int]] = []
    states_all: list[list] = []
    t_prev = None
    for f in frames:
        cands = [b for b in f.balls if b.conf >= min_conf]
        states = [None] + [(b.x, b.y, b.conf) for b in cands]
        em = [0.0]
        for b in cands:
            d = _near_player(f, b.x, b.y)
            bonus = near_bonus if d <= 1.5 else (0.3 * near_bonus if d <= 3.0 else -far_penalty)
            em.append(math.log(b.conf / 0.05) * 0.5 + bonus)
        dt = 0.125 if t_prev is None else max(f.t - t_prev, 1e-3)
        sc, bp = [], []
        for j, s in enumerate(states):
            best, arg = -1e9, 0
            for i, sp in enumerate(states_prev):
                if s is None:
                    tr = 0.0 if sp is None else -0.3
                elif sp is None:
                    tr = -miss_cost
                else:
                    d = math.hypot(s[0] - sp[0], s[1] - sp[1])
                    gate = base_px + speed_px_s * dt
                    tr = -(d / gate) ** 2 if d <= gate else -4.0
                v = score_prev[i] + tr
                if v > best:
                    best, arg = v, i
            sc.append(best + em[j]); bp.append(arg)
        back.append(bp); states_all.append(states)
        states_prev, score_prev, t_prev = states, sc, f.t
    # backtrack
    obs: dict[float, tuple[float, float]] = {}
    if frames:
        j = max(range(len(score_prev)), key=lambda k: score_prev[k])
        for k in range(len(frames) - 1, -1, -1):
            s = states_all[k][j]
            if s is not None:
                obs[frames[k].t] = (s[0], s[1])
            j = back[k][j]
    times = [f.t for f in frames]
    out: dict[float, tuple[float, float, bool]] = {t: (*obs[t], True) for t in obs}
    ot = sorted(obs)
    for a, b in zip(ot, ot[1:]):
        if 0 < b - a <= max_gap:
            for t in times:
                if a < t < b:
                    w = (t - a) / (b - a)
                    out[t] = (obs[a][0] + w * (obs[b][0] - obs[a][0]), obs[a][1] + w * (obs[b][1] - obs[a][1]), False)
    return out
