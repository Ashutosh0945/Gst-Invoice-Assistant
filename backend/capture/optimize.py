"""Camera capture pipeline (deterministic OpenCV, no AI):

    photo -> document detection -> auto crop + perspective correction -> orientation/deskew
          -> enhancement (shadow removal, contrast, denoise, sharpen) -> quality check -> OCR-ready image

The original image is never modified; every step returns a new image. Each step is
conservative: if the document outline can't be found confidently, the photo is NOT
cropped (cropping away invoice content is worse than leaving some background).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

MAX_SIDE = 2400          # work size; larger photos are scaled down (OCR doesn't need more)


@dataclass
class CaptureResult:
    original: np.ndarray
    enhanced: np.ndarray
    ocr_ready: np.ndarray
    steps: list[dict] = field(default_factory=list)       # what was actually done, in order
    quality: dict = field(default_factory=dict)            # metrics + warnings + verdict


def _resize(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    s = MAX_SIDE / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img.copy()


def _order(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype("float32")
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def detect_document(img: np.ndarray) -> tuple[np.ndarray | None, float]:
    """Finds the invoice's four corners. Returns (corners, fraction of the photo it covers)."""
    h, w = img.shape[:2]
    small_s = 800 / max(h, w)
    small = cv2.resize(img, (int(w * small_s), int(h * small_s))) if small_s < 1 else img
    small_s = min(small_s, 1.0)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    best, best_area = None, 0.0
    # Paper is usually brighter than the surface: try a brightness mask first, then edges.
    _, bright = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((5, 5), np.uint8), iterations=2)
    for mask in (bright, edges):
        cnts = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]   # OpenCV 3 returns 3 values, 4+ returns 2
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            area = cv2.contourArea(c) / (gray.shape[0] * gray.shape[1])
            if area < 0.2:
                break
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) != 4:
                approx = cv2.boxPoints(cv2.minAreaRect(c)).reshape(4, 1, 2)
            if cv2.isContourConvex(approx.astype(np.int32)) and area > best_area:
                best, best_area = approx, area
        if best is not None:
            break
    if best is None:
        return None, 0.0
    return _order(best / small_s), best_area


def warp(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    wdt = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    hgt = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    dst = np.array([[0, 0], [wdt - 1, 0], [wdt - 1, hgt - 1], [0, hgt - 1]], dtype="float32")
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (wdt, hgt), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_REPLICATE)


def _perspective_severity(quad: np.ndarray) -> float:
    """0 = perfect rectangle; grows with keystone distortion (max corner-angle deviation, degrees)."""
    devs = []
    for i in range(4):
        a, b, c = quad[i - 1], quad[i], quad[(i + 1) % 4]
        v1, v2 = a - b, c - b
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        devs.append(abs(90 - np.degrees(np.arccos(np.clip(cosang, -1, 1)))))
    return float(max(devs))


def _text_mask(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 15)


def orientation(gray: np.ndarray) -> int:
    """0 or 90/270 decision: text lines make horizontal projections much 'spikier' than vertical ones."""
    mask = _text_mask(cv2.resize(gray, None, fx=0.5, fy=0.5))
    h_var = np.var(mask.sum(axis=1).astype(float))
    v_var = np.var(mask.sum(axis=0).astype(float))
    return 90 if v_var > 1.6 * h_var else 0


def deskew_angle(gray: np.ndarray) -> float:
    """Small rotation of text lines (degrees), from the dominant angle of line segments. Capped at ±15°."""
    mask = _text_mask(gray)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3)))
    lines = cv2.HoughLinesP(mask, 1, np.pi / 720, threshold=120, minLineLength=gray.shape[1] // 6, maxLineGap=10)
    if lines is None:
        return 0.0
    # OpenCV builds differ: HoughLinesP may return shape (N, 1, 4) or (N, 4). reshape handles both.
    angs = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4)]
    angs = [a for a in angs if abs(a) <= 15]
    return float(np.median(angs)) if len(angs) >= 3 else 0.0


def rotate(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def enhance(img: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Returns (enhanced colour image, OCR-ready image, info). OCR-ready is grayscale; it is binarised
    only when lighting is uneven or contrast is weak, where thresholding is known to help OCR."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31)
    unevenness = float(np.std(bg) / (np.mean(bg) + 1e-6))
    flat = cv2.divide(gray, bg, scale=255)                                 # removes shadows/gradients
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l2 = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(cv2.divide(l, cv2.medianBlur(cv2.dilate(l, np.ones((7, 7), np.uint8)), 31), scale=255))
    enhanced = cv2.cvtColor(cv2.merge((l2, a, b)), cv2.COLOR_LAB2BGR)
    den = cv2.fastNlMeansDenoising(flat, None, h=7, templateWindowSize=7, searchWindowSize=21)
    sharp = cv2.addWeighted(den, 1.5, cv2.GaussianBlur(den, (0, 0), 1.2), -0.5, 0)
    contrast = float(np.std(gray))
    # Measured on test photos: modern OCR (Paddle/Rapid) reads clean grayscale as well as or better than
    # black-and-white, and thresholding lost characters on an angled desk photo. So binarise only in
    # extreme cases (very uneven light AND very low contrast) where greyscale text is barely separable.
    binarize = unevenness > 0.3 and contrast < 30
    # Measured on test photos (full extraction, 6 photo types): enhanced colour 19/24 fields, sharpened grayscale 18,
    # raw photo 17. So the enhanced colour image is what goes to OCR, unless lighting is extreme.
    ocr_ready = (cv2.cvtColor(cv2.adaptiveThreshold(sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12),
                              cv2.COLOR_GRAY2BGR) if binarize else enhanced)
    return enhanced, ocr_ready, {
        "lighting_unevenness": round(unevenness, 3), "binarized": binarize,
        "reason": "extremely uneven light and low contrast" if binarize else "enhanced colour reads best for OCR"}


def assess_quality(original: np.ndarray, doc: np.ndarray, coverage: float, found: bool, persp: float,
                   rotated: int, skew: float, light: dict) -> dict:
    gray = cv2.cvtColor(doc, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    sharp_img = cv2.resize(gray, (1000, int(1000 * h / w))) if w > 1000 else gray
    blur = float(cv2.Laplacian(sharp_img, cv2.CV_64F).var())
    brightness = float(np.mean(cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)))
    min_side = min(h, w)
    est_dpi = round(w / 8.27)                                      # assuming an A4-width invoice
    warnings = []

    def warn(code, sev, msg):
        warnings.append({"code": code, "severity": sev, "message": msg})

    if blur < 60:
        warn("blurry", "high", "The photo is blurry; text may not be readable. Hold the phone steady and retake.")
    elif blur < 150:
        warn("slightly_blurry", "medium", "The photo is slightly soft; small text may be misread.")
    if brightness < 70:
        warn("low_light", "high" if brightness < 45 else "medium", "The photo is dark. Retake in better light.")
    elif brightness > 240 and float((gray < 128).mean()) < 0.003:   # white paper is bright; warn only if text is washed out
        warn("overexposed", "medium", "The photo is very bright; faint text may be washed out.")
    if light["lighting_unevenness"] > 0.18:
        warn("shadows", "medium", "Strong shadows or uneven lighting detected; they were reduced automatically.")
    if min_side < 700:
        warn("low_resolution", "high" if min_side < 500 else "medium", f"Low resolution ({w}×{h}px). Move closer or use a higher camera setting.")
    border = np.concatenate([gray[:8].ravel(), gray[-8:].ravel(), gray[:, :8].ravel(), gray[:, -8:].ravel()])
    already_cropped = float(np.mean(border)) > 200          # white margins all round = a scan / already cropped
    if not found and not already_cropped:
        warn("no_document_edges", "low", "Couldn't find the invoice's edges, so the photo wasn't cropped. Fill the frame with the invoice for best results.")
    elif coverage < 0.35:
        warn("small_in_frame", "medium", "The invoice fills only a small part of the photo; move closer.")
    if found and persp > 25:
        warn("perspective", "medium", "The photo was taken at a steep angle; it was straightened, but very angled photos lose detail.")
    if found and coverage > 0.985:
        warn("possibly_cut_off", "medium", "The invoice touches the photo's edges; make sure no part of it is cut off.")
    score = 100
    for wn in warnings:
        score -= {"high": 35, "medium": 15, "low": 5}[wn["severity"]]
    verdict = "poor" if any(x["severity"] == "high" for x in warnings) else "fair" if warnings else "good"
    return {"verdict": verdict, "score": max(0, score), "warnings": warnings, "metrics": {
        "sharpness": round(blur, 1), "brightness": round(brightness, 1), "lighting_unevenness": light["lighting_unevenness"],
        "width_px": w, "height_px": h, "estimated_dpi": est_dpi, "document_found": found,
        "document_coverage_pct": round(100 * coverage, 1), "perspective_deg": round(persp, 1),
        "rotated_deg": rotated, "deskew_deg": round(skew, 2)}}


def optimize(image_bgr: np.ndarray) -> CaptureResult:
    original = image_bgr
    img = _resize(image_bgr)
    steps = []
    quad, coverage = detect_document(img)
    found = quad is not None and coverage < 0.985
    persp = _perspective_severity(quad) if quad is not None else 0.0
    if found:
        img = warp(img, quad)
        steps.append({"step": "Detect & crop document", "done": True, "detail": f"Invoice covers {round(100 * coverage)}% of the photo; background removed."})
        steps.append({"step": "Perspective correction", "done": persp > 2, "detail": f"Corner distortion {persp:.1f}°" + (" corrected." if persp > 2 else " (already straight).")})
    else:
        steps.append({"step": "Detect & crop document", "done": False, "detail": "Edges not found confidently; kept the full photo."})
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rot = orientation(gray)
    if rot:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    skew = deskew_angle(gray)
    if abs(skew) > 0.4:
        img = rotate(img, skew)
    steps.append({"step": "Orientation & deskew", "done": bool(rot) or abs(skew) > 0.4,
                  "detail": (f"Rotated 90°. " if rot else "") + (f"Straightened by {skew:.1f}°." if abs(skew) > 0.4 else "Text lines already level.")})
    enhanced, ocr_ready, light = enhance(img)
    steps.append({"step": "Enhancement", "done": True, "detail": "Shadows evened out, contrast and sharpness improved; "
                  + ("converted to black-and-white for OCR (" + light["reason"] + ")." if light["binarized"] else "kept in colour for OCR (" + light["reason"] + ").")})
    quality = assess_quality(_resize(original), img, coverage, found, persp, rot, skew, light)
    steps.append({"step": "Quality check", "done": True, "detail": f"Verdict: {quality['verdict']} ({quality['score']}/100)."})
    return CaptureResult(original=original, enhanced=enhanced, ocr_ready=ocr_ready, steps=steps, quality=quality)


def to_jpeg(img: np.ndarray, quality: int = 85, max_side: int = 1600) -> bytes:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""
