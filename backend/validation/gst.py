"""Deterministic GST primitives: GSTIN structure + checksum, state codes, rate slabs."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

GSTIN_RE = re.compile(r"^(\d{2})([A-Z]{5}\d{4}[A-Z])([1-9A-Z])Z([0-9A-Z])$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
    "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman & Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Centre Jurisdiction",
}
_NAME_TO_CODE = {v.lower(): k for k, v in STATE_CODES.items()}
_NAME_TO_CODE.update({"orissa": "21", "pondicherry": "34", "jammu and kashmir": "01",
                      "andaman and nicobar islands": "35", "new delhi": "07"})


def gstin_checksum(first14: str) -> str:
    """GSTIN check character: base-36 Luhn-style mod-36 over the first 14 characters."""
    factor, total = 2, 0
    for ch in reversed(first14):
        digit = factor * _CHARS.index(ch)
        factor = 1 if factor == 2 else 2
        total += digit // 36 + digit % 36
    return _CHARS[(36 - total % 36) % 36]


def gstin_format_ok(gstin: str | None) -> bool:
    return bool(gstin and GSTIN_RE.match(gstin.strip().upper()))


def gstin_valid(gstin: str | None) -> bool:
    """Structure + known state code + checksum."""
    if not gstin_format_ok(gstin):
        return False
    g = gstin.strip().upper()
    return g[:2] in STATE_CODES and gstin_checksum(g[:14]) == g[14]


def gstin_state(gstin: str | None) -> str | None:
    return gstin.strip().upper()[:2] if gstin_format_ok(gstin) else None


def gstin_pan(gstin: str | None) -> str | None:
    return gstin.strip().upper()[2:12] if gstin_format_ok(gstin) else None


def state_code_from_text(text: str | None) -> str | None:
    """'27', '27-Maharashtra', 'Maharashtra (27)', 'Maharashtra' -> '27'."""
    if not text:
        return None
    m = re.search(r"\b(\d{2})\b", text)
    if m and m.group(1) in STATE_CODES:
        return m.group(1)
    t = re.sub(r"[^a-z& ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    for name, code in sorted(_NAME_TO_CODE.items(), key=lambda kv: -len(kv[0])):
        if name in t:
            return code
    return None


# --- GST rate slabs --------------------------------------------------------------------
# GST 2.0 (56th Council, notified 17-Sep-2025) took effect on 22-Sep-2025: the 12% and 28%
# slabs were removed for most goods/services; 40% was introduced for sin/luxury goods.
# Special low rates (0.25% rough diamonds, 1.5%/3% precious items) are kept as valid slabs.
# ASSUMPTION TO VERIFY against current CBIC notifications before relying on it for compliance.
GST_2_EFFECTIVE = date(2025, 9, 22)
GST_LAUNCH = date(2017, 7, 1)
_D = Decimal
LEGACY_SLABS = frozenset(_D(x) for x in ("0", "0.25", "1.5", "3", "5", "12", "18", "28"))
CURRENT_SLABS = frozenset(_D(x) for x in ("0", "0.25", "1.5", "3", "5", "18", "40"))
_LEGACY_ONLY = LEGACY_SLABS - CURRENT_SLABS


def slab_status(rate: Decimal, on: date | None) -> str:
    """'ok' | 'legacy_after_cutover' | 'invalid'."""
    r = rate.normalize()
    if on is None:
        return "ok" if (r in LEGACY_SLABS or r in CURRENT_SLABS) else "invalid"
    if on >= GST_2_EFFECTIVE:
        if r in CURRENT_SLABS:
            return "ok"
        return "legacy_after_cutover" if r in _LEGACY_ONLY else "invalid"
    return "ok" if r in LEGACY_SLABS else "invalid"
