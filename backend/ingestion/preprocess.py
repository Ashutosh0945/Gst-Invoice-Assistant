"""OpenCV preprocessing: deskew, denoise, and contrast-normalize a page image
before OCR. Every operation returns a NEW array; callers keep the original.

cv2 is imported lazily (not at module load time) and every function here
degrades gracefully if it isn't importable -- e.g. on Vercel's serverless
runtime, opencv-python-headless can fail to import when a system shared
library (libGL.so.1 and friends) isn't present in that minimal environment,
even though the "headless" wheel doesn't need a display. Since deskewing is
purely a quality improvement for OCR (not required for extraction to run at
all -- native-text PDFs never call these functions in the first place), a
missing cv2 should mean "skip deskewing," not "crash every invoice upload."
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _try_import_cv2():
    try:
        import cv2
        return cv2
    except ImportError as exc:
        logger.warning(
            "opencv (cv2) is not available in this environment (%s); "
            "skipping deskew/denoise preprocessing and using the page image as-is.",
            exc,
        )
        return None


def to_gray(img: np.ndarray, cv2) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def denoise(gray: np.ndarray, cv2) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10)


def binarize(gray: np.ndarray, cv2) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def estimate_skew_angle(gray: np.ndarray, cv2) -> float:
    """Estimate skew via minAreaRect over ink pixel coordinates. Returns degrees."""
    inv = 255 - gray
    coords = np.column_stack(np.where(inv > 30))
    if coords.shape[0] < 50:
        return 0.0
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    if angle < -45:
        angle = 90 + angle
    # Clamp: extreme values usually mean the estimate is unreliable for a text page.
    if abs(angle) > 15:
        return 0.0
    return float(angle)


def rotate(img: np.ndarray, angle_deg: float, cv2) -> np.ndarray:
    if abs(angle_deg) < 0.05:
        return img
    h, w = img.shape[:2]
    center = (w / 2, h / 2)
    m = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def preprocess_for_ocr(img: np.ndarray) -> tuple[np.ndarray, float]:
    """Returns (deskewed_bgr_image, angle_applied). Deskew happens on the color
    image (so downstream OCR bbox coordinates stay in the same space);
    denoise/binarize are used only internally to *estimate* skew.

    Falls back to returning the image unchanged (angle 0.0) if cv2 isn't
    importable in this environment.
    """
    cv2 = _try_import_cv2()
    if cv2 is None:
        return img, 0.0

    gray = to_gray(img, cv2)
    denoised = denoise(gray, cv2)
    angle = estimate_skew_angle(binarize(denoised, cv2), cv2)
    deskewed = rotate(img, angle, cv2)
    return deskewed, angle
