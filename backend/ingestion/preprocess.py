"""OpenCV preprocessing: deskew, denoise, and contrast-normalize a page image
before OCR. Every operation returns a NEW array; callers keep the original.
"""
from __future__ import annotations

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, h=10)


def binarize(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )


def estimate_skew_angle(gray: np.ndarray) -> float:
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


def rotate(img: np.ndarray, angle_deg: float) -> np.ndarray:
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
    """
    gray = to_gray(img)
    denoised = denoise(gray)
    angle = estimate_skew_angle(binarize(denoised))
    deskewed = rotate(img, angle)
    return deskewed, angle
