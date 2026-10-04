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
    """PaddleOCR if installed (requirements-ml.txt); else RapidOCR (the same PaddleOCR models on the
    lighter onnxruntime, requirements-ocr.txt); else OCRUnavailable."""
    return _engine_cached()


@lru_cache(maxsize=1)
def _engine_cached():
    try:
        from paddleocr import PaddleOCR
        return ("paddle", PaddleOCR(use_angle_cls=True, lang="en", show_log=False))
    except ImportError:
        pass
    try:
        from rapidocr_onnxruntime import RapidOCR
        return ("rapid", RapidOCR())
    except ImportError as exc:
        raise OCRUnavailable("No OCR engine installed. Install requirements-ml.txt (PaddleOCR) or "
                             "requirements-ocr.txt (RapidOCR) to read photos and scanned PDFs.") from exc


def engine_name() -> str | None:
    """Which OCR engine is available, without loading models (used by System Health)."""
    import importlib.util
    if importlib.util.find_spec("paddleocr"):
        return "PaddleOCR"
    if importlib.util.find_spec("rapidocr_onnxruntime"):
        return "RapidOCR (PaddleOCR models on onnxruntime)"
    return None


def run_ocr(image_bgr: np.ndarray) -> list[OCRWord]:
    """Runs OCR on a BGR image and returns line-level boxes with text + confidence."""
    kind, engine = _get_engine()
    words: list[OCRWord] = []
    if kind == "paddle":
        result = engine.ocr(image_bgr, cls=True)
        lines = result[0] if result and result[0] is not None else []
        items = [(box, text, conf) for box, (text, conf) in lines]
    else:
        result, _ = engine(image_bgr)
        items = [(box, text, conf) for box, text, conf in (result or [])]
    for box, text, conf in items:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        words.append(OCRWord(text=text, bbox=(min(xs), min(ys), max(xs), max(ys)), conf=float(conf)))
    return words
