"""Kit-colour clustering of detected people into home / away / other."""
from __future__ import annotations

import numpy as np

HOME, AWAY, OTHER = "home", "away", "other"


def bgr_to_lab(bgr: tuple[int, int, int]) -> np.ndarray:
    import cv2
    return cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2LAB)[0, 0].astype(float)


def kmeans(x: np.ndarray, k: int, iters: int = 50, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Small deterministic k-means (k-means++ init). Returns (centres, labels)."""
    rng = np.random.default_rng(seed)
    c = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = np.min(((x[:, None, :] - np.array(c)[None]) ** 2).sum(-1), axis=1)
        c.append(x[rng.choice(len(x), p=d / d.sum())] if d.sum() > 0 else x[rng.integers(len(x))])
    c = np.array(c, dtype=float)
    lab = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        lab = ((x[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
        new = np.array([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
        if np.allclose(new, c):
            break
        c = new
    return c, lab


class TeamModel:
    """Two team centres in Lab space; anything far from both is ``other`` (GK, referee, staff)."""

    def __init__(self, home: np.ndarray, away: np.ndarray, max_dist: float):
        self.home, self.away, self.max_dist = np.asarray(home, float), np.asarray(away, float), max_dist

    def assign(self, color) -> str:
        if color is None:
            return OTHER
        c = np.asarray(color, float)
        dh, da = np.linalg.norm(c - self.home), np.linalg.norm(c - self.away)
        if min(dh, da) > self.max_dist:
            return OTHER
        return HOME if dh <= da else AWAY

    @classmethod
    def fit(cls, colors: list, home_hint=None, away_hint=None, k: int = 4) -> "TeamModel":
        """Cluster torso colours; the two biggest clusters are the teams.

        ``home_hint`` / ``away_hint`` are BGR reference kit colours; the team
        clusters are mapped to home/away by the closer hint (else by size order).
        """
        x = np.array([c for c in colors if c is not None], dtype=float)
        if len(x) < k * 3:
            raise ValueError("not enough coloured detections to cluster teams")
        cen, lab = kmeans(x, k)
        sizes = np.bincount(lab, minlength=k)
        a, b = np.argsort(-sizes)[:2]
        ca, cb = cen[a], cen[b]
        if home_hint is not None and away_hint is not None:
            h, w = bgr_to_lab(home_hint), bgr_to_lab(away_hint)
            if np.linalg.norm(ca - h) + np.linalg.norm(cb - w) > np.linalg.norm(ca - w) + np.linalg.norm(cb - h):
                ca, cb = cb, ca
        spread = np.percentile(np.concatenate([np.linalg.norm(x[lab == a] - cen[a], axis=1),
                                               np.linalg.norm(x[lab == b] - cen[b], axis=1)]), 90)
        return cls(ca, cb, max(float(spread) * 1.3, 12.0))
