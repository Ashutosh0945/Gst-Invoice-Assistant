"""E9: evaluation on REAL OCR output (RapidOCR = PaddleOCR models on onnxruntime), not simulated noise.
    python -m research.real_ocr ocr <start> <end>   # render + OCR documents [start, end) and cache words
    python -m research.real_ocr eval                # score all extractors on the cached OCR output
Conditions: 'scan' (clean 150-dpi render), 'photo' (rendered page placed on a desk with perspective, shadow,
blur and JPEG compression), 'photo+capture' (the photo after the app's capture optimisation pipeline).
Documents: unseen layouts 16-23. Models: the E8 run-1 models trained on layouts 0-15 only."""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np
import pymupdf

from research.gst_synth import generate
from research.run_experiments import EXTRACTORS, OUT, score

CACHE = OUT / "e9_ocr_cache"
CACHE.mkdir(exist_ok=True)
DOCS = [(lid, 950_000 + k) for lid in range(16, 24) for k in range(3)]


def render(pdf: bytes) -> np.ndarray:
    pix = pymupdf.open(stream=pdf)[0].get_pixmap(dpi=150)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3][:, :, ::-1].copy()


def photo(img: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    H, W = int(h * 1.35), int(w * 1.35)
    bg = np.clip(np.full((H, W, 3), (60, 95, 140), np.float32) + rng.normal(0, 12, (H, W, 1)), 0, 255).astype(np.uint8)
    j = lambda: rng.uniform(-0.04, 0.04)  # noqa: E731
    dst = np.float32([[W * (0.12 + j()), H * (0.11 + j())], [W * (0.88 + j()), H * (0.12 + j())],
                      [W * (0.90 + j()), H * (0.89 + j())], [W * (0.10 + j()), H * (0.88 + j())]])
    M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), dst)
    paper = cv2.warpPerspective(img, M, (W, H)); mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (W, H))
    out = np.where(mask[..., None] > 0, paper, bg).astype(np.float32)
    out *= np.tile(np.linspace(rng.uniform(0.55, 0.8), 1.0, W, dtype=np.float32), (H, 1))[..., None]   # shadow gradient
    out = cv2.GaussianBlur(np.clip(out, 0, 255).astype(np.uint8), (0, 0), rng.uniform(0.6, 1.2))
    ok, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)


def ocr_words(img: np.ndarray):
    """RapidOCR returns text LINES; split each into words with proportional boxes (what an OCR word API gives)."""
    from rapidocr_onnxruntime import RapidOCR
    global _ENG
    if "_ENG" not in globals():
        _ENG = RapidOCR()
    res, _ = _ENG(img)
    words = []
    for box, text, conf in res or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        toks = text.split()
        total = sum(len(t) for t in toks) + max(0, len(toks) - 1)
        x = x0
        for t in toks:
            wd = (x1 - x0) * len(t) / max(1, total)
            words.append([t, [x, y0, x + wd, y1]])
            x += wd + (x1 - x0) / max(1, total)
    return words, img.shape[1], img.shape[0]


def build(start: int, end: int):
    for lid, s in DOCS[start:end]:
        d = generate(lid, s)
        scan = render(d.pdf)
        ph = photo(scan, s)
        conds = {"scan": scan, "photo": ph}
        try:
            from backend.capture.optimize import optimize
            conds["photo+capture"] = optimize(ph).ocr_ready
        except Exception as exc:  # noqa: BLE001
            print("capture failed:", exc)
        rec = {"layout": lid, "seed": s, "conditions": {}}
        for c, im in conds.items():
            w, W, H = ocr_words(im)
            rec["conditions"][c] = {"words": w, "width": W, "height": H}
        (CACHE / f"L{lid}_{s}.json").write_text(json.dumps(rec))
        print("cached", lid, s, {c: len(v["words"]) for c, v in rec["conditions"].items()})


def evaluate():
    from backend.extraction import learned as K
    from research.rigor import crf_extract  # noqa: F401  (models below are NumPy exports)
    load = lambda p: K.load_model.__wrapped__(str(OUT / p))  # noqa: E731
    models = {"Linear model (ablation)": load("e9_model_lr.npz"), "LayoutKIE-CRF (ours)": load("e9_model_crf.npz")}
    res = {}
    for f in sorted(CACHE.glob("*.json")):
        rec = json.loads(f.read_text())
        truth = generate(rec["layout"], rec["seed"]).truth
        for c, v in rec["conditions"].items():
            words = [(t, tuple(b)) for t, b in v["words"]]
            outs = {n: EXTRACTORS[n](words, v["width"], v["height"], None) for n in ("Regex rules", "Layout heuristic", "Rules ensemble")}
            outs["Layout heuristic + normaliser"] = EXTRACTORS["Layout heuristic"](K.normalize_ocr_tokens(words), v["width"], v["height"], None)
            outs["Regex rules + normaliser"] = EXTRACTORS["Regex rules"](K.normalize_ocr_tokens(words), v["width"], v["height"], None)
            outs.update({n: K.extract(words, v["width"], v["height"], m) for n, m in models.items()})
            outs["LayoutKIE-CRF (no normaliser)"] = K.extract(words, v["width"], v["height"], models["LayoutKIE-CRF (ours)"], normalize=False)
            for n, inv in outs.items():
                h, it = score(inv, truth)
                a = res.setdefault(c, {}).setdefault(n, {"hits": 0, "total": 0, "perfect": 0, "docs": 0, "header_hits": 0, "header_total": 0})
                a["hits"] += sum(ok for _, ok in h + it); a["total"] += len(h + it); a["perfect"] += all(ok for _, ok in h + it); a["docs"] += 1
                a["header_hits"] += sum(ok for _, ok in h); a["header_total"] += len(h)
    out = {c: {n: {"field_acc": round(a["hits"] / a["total"], 4), "header_acc": round(a["header_hits"] / a["header_total"], 4),
                   "perfect_docs": round(a["perfect"] / a["docs"], 4), "docs": a["docs"]} for n, a in v.items()} for c, v in res.items()}
    (OUT / "e9_real_ocr.json").write_text(json.dumps(out, indent=2))
    for c, v in out.items():
        print(c, {n: (x["field_acc"], x["header_acc"]) for n, x in v.items()})


if __name__ == "__main__":
    build(int(sys.argv[2]), int(sys.argv[3])) if sys.argv[1] == "ocr" else evaluate()
