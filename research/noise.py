"""OCR-noise simulation, so models and rules can be compared on 'photo-like' input without running OCR.
Applies, at a given rate: character confusions (0/O, 1/l/I, 5/S, 8/B, ,/.), dropped characters, word splits
and merges, bounding-box jitter and a small page rotation (skew). Labels are carried through."""
from __future__ import annotations

import math
import random

CONF = {"0": "O", "O": "0", "1": "l", "l": "1", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", ",": ".", ".": ",", "2": "Z", "6": "G"}


def add_noise(words, labels, rate: float, seed: int, width: float, height: float):
    if rate <= 0:
        return list(words), list(labels)
    r = random.Random(seed)
    ang = math.radians(r.uniform(-1, 1) * rate * 15)
    cx, cy = width / 2, height / 2
    rot = lambda x, y: (cx + (x - cx) * math.cos(ang) - (y - cy) * math.sin(ang), cy + (x - cx) * math.sin(ang) + (y - cy) * math.cos(ang))  # noqa: E731
    out_w, out_l = [], []
    i = 0
    while i < len(words):
        t, (x0, y0, x1, y1) = words[i]
        lab = labels[i]
        if r.random() < rate and len(t) > 1:
            k = r.randrange(len(t))
            ch = t[k]
            t = t[:k] + (CONF.get(ch, "") if r.random() < 0.8 else "") + t[k + 1:] or t
        if r.random() < rate / 3 and i + 1 < len(words) and abs(words[i + 1][1][1] - y0) < 3:     # merge with next word
            t2, (a0, b0, a1, b1) = words[i + 1]
            t, x1, y1 = t + t2, a1, max(y1, b1)
            i += 1
        if r.random() < rate / 3 and len(t) > 5:                                                   # split
            k = len(t) // 2
            xm = x0 + (x1 - x0) * k / len(t)
            parts = [(t[:k], (x0, y0, xm, y1), lab), (t[k:], (xm, y0, x1, y1), ("I-" + lab[2:]) if lab != "O" else "O")]
        else:
            parts = [(t, (x0, y0, x1, y1), lab)]
        for pt, (a0, b0, a1, b1), pl in parts:
            j = lambda: r.uniform(-1.5, 1.5) * rate * 10  # noqa: E731
            p0, p1 = rot(a0 + j(), b0 + j()), rot(a1 + j(), b1 + j())
            out_w.append((pt, (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))))
            out_l.append(pl)
        i += 1
    return out_w, out_l
