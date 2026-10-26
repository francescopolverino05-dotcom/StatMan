"""Camera motion from global frame-to-frame shift (phase correlation).

The broadcast here is an auto-tracking camera (XbotGo) that follows the ball,
so pan velocity is a smoothed proxy of ball motion: a pass or clearance shows
up as an onset / reversal of pan. Cheap: one downscaled phase correlation per
sampled frame.
"""
from __future__ import annotations

import numpy as np

from .extract import iter_frames


def pan_series(video, fps: float = 8.0, start: float = 0.0, duration: float | None = None,
               scale: float = 0.25) -> list[tuple[float, float, float]]:
    """Return [(t, dx_px_per_s, dy_px_per_s)] in full-resolution pixels, between consecutive samples."""
    import cv2
    out = []
    prev = None
    win = None
    for t, img in iter_frames(video, fps, start, duration):
        H, W = img.shape[:2]
        g = cv2.cvtColor(cv2.resize(img[: int(H * 0.92)], None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if win is None:
            win = cv2.createHanningWindow(g.shape[::-1], cv2.CV_32F)
        if prev is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev[1], g, win)
            dt = t - prev[0]
            out.append((round(t, 3), -dx / scale / dt, -dy / scale / dt))
        prev = (t, g)
    return out


def pan_events(series, smooth: int = 3, min_change: float = 10.0, min_sep: float = 0.5) -> list[tuple[float, float]]:
    """Moments where horizontal pan velocity changes sharply (onset, stop, reversal).

    Returns [(t, strength)] where strength is the |change| in px/s across the moment.
    """
    if len(series) < 2 * smooth + 2:
        return []
    t = np.array([s[0] for s in series])
    vx = np.array([s[1] for s in series])
    k = np.ones(smooth) / smooth
    v = np.convolve(vx, k, mode="same")
    # change between the mean velocity after and before each sample
    ch = np.zeros_like(v)
    for i in range(smooth, len(v) - smooth):
        ch[i] = v[i + 1:i + 1 + smooth].mean() - v[i - smooth:i].mean()
    a = np.abs(ch)
    ev = []
    for i in range(1, len(a) - 1):
        if a[i] >= min_change and a[i] >= a[i - 1] and a[i] >= a[i + 1]:
            if ev and t[i] - ev[-1][0] < min_sep:
                if a[i] > ev[-1][1]:
                    ev[-1] = (float(t[i]), float(a[i]))
                continue
            ev.append((float(t[i]), float(a[i])))
    return ev
