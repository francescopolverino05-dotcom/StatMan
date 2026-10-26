"""Phase 2 (experimental, NOT wired into the live path): label phase-1 candidate moments with a vision LLM.

Each moment becomes one composite image: a downscaled full frame at t (camera centre and candidate player boxed)
plus three zoomed crops around the candidate player / ball at t-0.5, t, t+0.5 s. Moments are batched per call.
Spending is guarded by a hard cap checked before every call (worst-case cost of the next call included).
"""
from __future__ import annotations

import base64
import json
import os
import time

import cv2
import numpy as np

EVENT_TYPES = ["pass", "shot", "tackle", "interception", "clearance", "recovery", "throw-in", "dribble",
               "foul", "cross", "save", "no event"]
PRICE_IN, PRICE_OUT = 0.30e-6, 2.50e-6      # google/gemini-2.5-flash USD per token
TOKENS_PER_IMAGE = 1100                      # conservative (768x~560 -> up to 4 tiles of 258)


def _grab(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0) * 1000)
    ok, img = cap.read()
    return img if ok else None


def composite(cap, m: dict, burst=0.5, full_w=768, crop_wh=(240, 135)) -> np.ndarray | None:
    t = m["t"]
    img = _grab(cap, t)
    if img is None:
        return None
    H, W = img.shape[:2]
    cx, cy = m.get("ball_xy") or (W / 2, H * 0.6)
    full = img.copy()
    if m.get("player_box"):
        x0, y0, x1, y1 = map(int, m["player_box"]); cv2.rectangle(full, (x0, y0), (x1, y1), (0, 255, 255), 2)
    cv2.circle(full, (int(cx), int(cy)), 40, (0, 0, 255), 2)
    full = cv2.resize(full, (full_w, int(H * full_w / W)))
    cw, ch = crop_wh
    x0 = int(min(max(cx - cw / 2, 0), W - cw)); y0 = int(min(max(cy - ch / 2, 0), H - ch))
    crops = []
    for dt in (-burst, 0, burst):
        f = img if dt == 0 else _grab(cap, t + dt)
        c = f[y0:y0 + ch, x0:x0 + cw] if f is not None else np.zeros((ch, cw, 3), np.uint8)
        c = cv2.resize(c, (full_w // 3, int(ch * (full_w // 3) / cw)))
        cv2.putText(c, f"{dt:+.1f}s", (4, 16), 0, .5, (255, 255, 255), 1)
        crops.append(c)
    return np.vstack([full, np.hstack(crops)])


def prompt(facts: dict, ids: list[int]) -> str:
    f = facts.get("facts", facts)
    lu = f.get("lineups", {})
    def roster(side):
        return ", ".join(f"{p['number']} {p['name']}" for p in lu.get(side, []))
    return (
        "You label amateur football (soccer) video from a single wide side camera.\n"
        f"Home: {f.get('home_team')} in LIGHT BLUE shirts. Away: {f.get('away_team')} in BLACK shirts. "
        "Referee usually in red/other.\n"
        f"Home squad: {roster('home')}\nAway squad: {roster('away')}\n"
        "Each image is one candidate moment: TOP = full frame at time t (red circle = estimated ball area, yellow box "
        "= nearest detected player); BOTTOM = zoomed crops of that area at t-0.5s, t, t+0.5s.\n"
        "For each moment say who touched the ball at t (the on-ball action), or 'no event' if nobody plays the ball.\n"
        f"event in {EVENT_TYPES}; team 'home'|'away'|'unknown'; outcome 'success'|'fail'|'unknown'; "
        "shirt = number if readable else 'unknown'. Do not guess shirt numbers.\n"
        f"Moment ids in order: {ids}. Reply ONLY JSON: "
        '{"moments":[{"id":0,"team":"home","event":"pass","outcome":"success","shirt":"unknown"}]}'
    )


def build_batches(video, moments, facts, batch=8):
    cap = cv2.VideoCapture(str(video))
    out = []
    for i in range(0, len(moments), batch):
        ids = list(range(i, min(i + batch, len(moments))))
        content = [{"type": "text", "text": prompt(facts, ids)}]
        for j in ids:
            im = composite(cap, moments[j])
            if im is None:
                continue
            ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 80])
            content.append({"type": "text", "text": f"Moment id {j}:"})
            content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                                                               base64.b64encode(buf).decode()}})
        out.append((ids, content))
    cap.release()
    return out


def estimate(content, max_tokens) -> tuple[int, float]:
    n_img = sum(c["type"] == "image_url" for c in content)
    n_txt = sum(len(c["text"]) for c in content if c["type"] == "text") // 3
    tin = n_img * TOKENS_PER_IMAGE + n_txt
    return tin, tin * PRICE_IN + max_tokens * PRICE_OUT


def parse_reply(text: str) -> list[dict]:
    s = text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(s).get("moments", [])
    except Exception:
        return []


def run(batches, api_key, cap_usd, endpoint, model="google/gemini-2.5-flash", max_tokens=1200, poster=None, log=None):
    """Sends batches while spent + worst-case(next) <= cap_usd. Returns (labels by id, spent, calls)."""
    if poster is None:
        import requests
        poster = requests.post
    spent, calls, labels = 0.0, 0, {}
    for ids, content in batches:
        _, worst = estimate(content, max_tokens)
        if spent + worst > cap_usd:
            if log: log(f"stop: spent {spent:.4f} + worst {worst:.4f} > cap {cap_usd}")
            break
        body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "usage": {"include": True},
                "reasoning": {"max_tokens": 0}, "messages": [{"role": "user", "content": content}]}
        r = poster(endpoint, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=180)
        calls += 1
        j = r.json()
        u = j.get("usage") or {}
        spent += float(u.get("cost") or (u.get("prompt_tokens", 0) * PRICE_IN + u.get("completion_tokens", 0) * PRICE_OUT)
                       if u else worst)
        if log: log(f"call {calls} ids {ids[0]}-{ids[-1]} status {getattr(r, 'status_code', '?')} usage {u} spent {spent:.4f}")
        try:
            txt = j["choices"][0]["message"]["content"] or ""
        except Exception:
            txt = ""
        for d in parse_reply(txt):
            if isinstance(d, dict) and d.get("id") in ids:
                labels[d["id"]] = d
    return labels, spent, calls
