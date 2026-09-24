"""Find and decode QR codes on invoice page images.

zxing-cpp is the primary decoder: e-invoice QR codes carry an ~800-1200
character signed JWT (QR version 20+), which OpenCV's built-in detector
frequently fails to read. OpenCV is kept as a fallback so the module still
works if zxing-cpp is not installed.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def decode_qr_codes(image: np.ndarray) -> list[str]:
    """Returns the text of every QR code found on one page image (BGR or grayscale)."""
    texts: list[str] = []
    try:
        import zxingcpp

        for result in zxingcpp.read_barcodes(image):
            if result.text:
                texts.append(result.text)
        if texts:
            return texts
    except ImportError:
        logger.debug("zxing-cpp not installed; falling back to OpenCV QR detection.")
    except Exception as exc:  # noqa: BLE001 - a decoder crash must never fail the pipeline
        logger.warning("zxing-cpp failed on page image: %s", exc)

    try:
        import cv2

        ok, decoded, _points, _ = cv2.QRCodeDetector().detectAndDecodeMulti(image)
        if ok:
            texts.extend(t for t in decoded if t)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenCV QR detection failed: %s", exc)
    return texts


def looks_like_jwt(text: str) -> bool:
    parts = text.strip().split(".")
    return len(parts) == 3 and all(parts[:2]) and text.strip().startswith("eyJ")


def find_signed_qr(images: list[np.ndarray]) -> str | None:
    """First QR on any page whose content is a signed JWT (the e-invoice QR)."""
    for image in images:
        for text in decode_qr_codes(image):
            if looks_like_jwt(text):
                return text.strip()
    return None
