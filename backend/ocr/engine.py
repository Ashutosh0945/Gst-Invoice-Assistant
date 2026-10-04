"""OCR engine selection for invoice images and scanned PDFs.

Production on Vercel uses Google Cloud Vision when GOOGLE_VISION_API_KEY is set.
Local/self-hosted environments can still use PaddleOCR or RapidOCR as fallbacks.
Google Vision is called over HTTPS with httpx so no heavyweight OCR runtime is
needed inside the Vercel Python function.
"""
from __future__ import annotations

import base64
import logging
from functools import lru_cache
from typing import Any

import numpy as np

from backend.config import get_settings
from backend.schemas import OCRWord

logger = logging.getLogger(__name__)


class OCRUnavailable(RuntimeError):
    """Raised when a page needs OCR but no configured OCR engine is available."""


def _bbox(vertices: list[dict[str, Any]] | None) -> tuple[float, float, float, float]:
    """Convert Google Vision polygon vertices to x0,y0,x1,y1 pixel coordinates."""
    if not vertices:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [float(v.get("x", 0)) for v in vertices]
    ys = [float(v.get("y", 0)) for v in vertices]
    return (min(xs), min(ys), max(xs), max(ys))


def _google_words(payload: dict[str, Any]) -> list[OCRWord]:
    """Extract word-level OCR boxes from Vision DOCUMENT_TEXT_DETECTION output."""
    annotation = payload.get("fullTextAnnotation") or {}
    words: list[OCRWord] = []

    for page in annotation.get("pages", []):
        for block in page.get("blocks", []):
            for paragraph in block.get("paragraphs", []):
                for word in paragraph.get("words", []):
                    symbols = word.get("symbols", [])
                    text = "".join(str(s.get("text", "")) for s in symbols).strip()
                    if not text:
                        continue
                    conf = float(word.get("confidence", paragraph.get("confidence", 1.0)) or 0.0)
                    words.append(OCRWord(
                        text=text,
                        bbox=_bbox(word.get("boundingBox", {}).get("vertices")),
                        conf=max(0.0, min(1.0, conf)),
                    ))

    # Very old/odd Vision responses may omit the page hierarchy but still return
    # a top-level annotation. Keep extraction useful in that case.
    if not words and annotation.get("text"):
        words = [OCRWord(text=line.strip(), bbox=(0, 0, 0, 0), conf=0.8)
                 for line in annotation["text"].splitlines() if line.strip()]
    return words


def _run_google_vision(image_bgr: np.ndarray) -> list[OCRWord]:
    """Call Google Cloud Vision DOCUMENT_TEXT_DETECTION using a server-side API key."""
    settings = get_settings()
    api_key = settings.google_vision_api_key
    if not api_key:
        raise OCRUnavailable("Google Cloud Vision is not configured.")

    try:
        import cv2
        ok, encoded = cv2.imencode(".png", image_bgr)
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailable(f"Could not encode image for Google Vision: {type(exc).__name__}") from exc

    if not ok:
        raise OCRUnavailable("Could not encode invoice image for Google Vision.")

    body = {
        "requests": [{
            "image": {"content": base64.b64encode(encoded.tobytes()).decode("ascii")},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
        }]
    }

    try:
        import httpx
        response = httpx.post(
            "https://vision.googleapis.com/v1/images:annotate",
            params={"key": api_key},
            json=body,
            timeout=settings.google_vision_timeout_s,
        )
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailable(f"Google Vision request failed: {type(exc).__name__}") from exc

    if response.status_code != 200:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))
        except Exception:  # noqa: BLE001
            detail = response.text[:200]
        raise OCRUnavailable(f"Google Vision returned HTTP {response.status_code}: {detail}")

    try:
        result = response.json()
        api_error = result.get("responses", [{}])[0].get("error", {})
        if api_error.get("message"):
            raise OCRUnavailable(f"Google Vision error: {api_error['message']}")
        return _google_words(result.get("responses", [{}])[0])
    except OCRUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OCRUnavailable(f"Invalid Google Vision response: {type(exc).__name__}") from exc


@lru_cache(maxsize=1)
def _get_engine():
    """Return the first configured OCR engine.

    Google Vision is preferred on Vercel because it does not require PaddleOCR,
    RapidOCR, ONNX Runtime, or model files inside the serverless bundle.
    """
    settings = get_settings()
    if settings.google_vision_api_key:
        return ("google", None)
    return _get_local_engine()


@lru_cache(maxsize=1)
def _get_local_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
        return ('rapid', RapidOCR())
    except ImportError:
        pass

    try:
        from paddleocr import PaddleOCR
        return ('paddle', PaddleOCR(lang='en'))
    except Exception as exc:
        raise OCRUnavailable(
            'No compatible local OCR engine is available. '
            'Install rapidocr_onnxruntime.'
        ) from exc

def engine_name() -> str | None:
    """Return the configured OCR engine without loading a local OCR model."""
    import importlib.util

    settings = get_settings()
    if settings.google_vision_api_key:
        return "Google Cloud Vision"
    if importlib.util.find_spec("paddleocr"):
        return "PaddleOCR"
    if importlib.util.find_spec("rapidocr_onnxruntime"):
        return "RapidOCR (PaddleOCR models on onnxruntime)"
    return None


def run_ocr(image_bgr: np.ndarray) -> list[OCRWord]:
    """Run OCR on a BGR image and return word-level boxes with confidence."""
    kind, engine = _get_engine()

    if kind == "google":
        return _run_google_vision(image_bgr)

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
        words.append(OCRWord(
            text=text,
            bbox=(min(xs), min(ys), max(xs), max(ys)),
            conf=float(conf),
        ))
    return words