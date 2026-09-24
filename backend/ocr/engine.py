"""PaddleOCR wrapper. Imported lazily so the rest of the system runs without
paddleocr/paddlepaddle installed (see requirements-ml.txt) — only pages that
actually need OCR (scanned/image invoices) touch this module.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from backend.config import get_settings
from backend.schemas import OCRWord

logger = logging.getLogger(__name__)


class OCRUnavailable(RuntimeError):
    """Raised when a page needs OCR but paddleocr isn't installed."""


@lru_cache(maxsize=1)
def _get_engine():
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:  # pragma: no cover - exercised only without paddleocr installed
        raise OCRUnavailable(
            "paddleocr is not installed. Install requirements-ml.txt to OCR scanned "
            "invoices, or supply only born-digital PDFs."
        ) from exc

    settings = get_settings()
    return PaddleOCR(use_angle_cls=True, lang=settings.ocr_lang, use_gpu=settings.ocr_use_gpu, show_log=False)


def run_ocr(image_bgr: np.ndarray) -> list[OCRWord]:
    """Runs PaddleOCR on a BGR image and returns word/line-level boxes with text + confidence."""
    engine = _get_engine()
    result = engine.ocr(image_bgr, cls=True)
    words: list[OCRWord] = []
    if not result or result[0] is None:
        return words
    for box, (text, conf) in result[0]:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append(OCRWord(text=text, bbox=(min(xs), min(ys), max(xs), max(ys)), conf=float(conf)))
    return words
