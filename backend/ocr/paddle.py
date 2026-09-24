"""PaddleOCR wrapper (v2 and v3 APIs). Heavy import is lazy so the rest of the system runs without it.

PaddleOCR returns *line*-level boxes. LayoutLMv3 and the table parser want word-level boxes, so each
line is split into words with box widths proportional to character counts.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from backend.config import get_settings
from backend.schemas import OCRWord

log = logging.getLogger(__name__)


def split_line_to_words(text: str, box: tuple[float, float, float, float], conf: float) -> list[OCRWord]:
    x0, y0, x1, y1 = box
    words = text.split()
    if not words:
        return []
    total = sum(len(w) for w in words) + max(len(words) - 1, 0)   # count separators as one char
    cur, out = x0, []
    for w in words:
        wx1 = cur + (x1 - x0) * len(w) / total
        out.append(OCRWord(text=w, bbox=(cur, y0, wx1, y1), conf=conf))
        cur = wx1 + (x1 - x0) / total
    return out


@lru_cache
def _engine():
    from paddleocr import PaddleOCR  # noqa: WPS433 (lazy)
    s = get_settings()
    try:  # PaddleOCR >= 3
        return PaddleOCR(lang=s.ocr_lang, use_doc_orientation_classify=False, use_doc_unwarping=False,
                         use_textline_orientation=False, device="gpu" if s.ocr_use_gpu else "cpu")
    except TypeError:  # PaddleOCR 2.x
        return PaddleOCR(lang=s.ocr_lang, use_angle_cls=True, use_gpu=s.ocr_use_gpu, show_log=False)


def _poly_to_box(poly) -> tuple[float, float, float, float]:
    a = np.asarray(poly, dtype=float).reshape(-1, 2)
    return float(a[:, 0].min()), float(a[:, 1].min()), float(a[:, 0].max()), float(a[:, 1].max())


def run_ocr(image_bgr: np.ndarray) -> list[OCRWord]:
    eng = _engine()
    words: list[OCRWord] = []
    if hasattr(eng, "predict"):                       # v3 API
        for res in eng.predict(image_bgr):
            data = res.json.get("res", res.json) if hasattr(res, "json") else dict(res)
            texts, scores = data["rec_texts"], data["rec_scores"]
            boxes = data.get("rec_boxes")
            polys = data.get("rec_polys")
            for i, (t, sc) in enumerate(zip(texts, scores)):
                box = tuple(float(v) for v in boxes[i]) if boxes is not None and len(boxes) > i else _poly_to_box(polys[i])
                words += split_line_to_words(t, box, float(sc))
    else:                                             # v2 API
        for page in eng.ocr(image_bgr, cls=True) or []:
            for poly, (t, sc) in page or []:
                words += split_line_to_words(t, _poly_to_box(poly), float(sc))
    return words
