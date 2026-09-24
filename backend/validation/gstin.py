"""GSTIN structural validation (format + checksum) — this is a data-quality
check, not a call to the GSTN portal (no live GSTIN-status API is used here).
"""
from __future__ import annotations

import re

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]$")
_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def is_well_formed(gstin: str | None) -> bool:
    if not gstin:
        return False
    return bool(GSTIN_RE.match(gstin.strip().upper()))


def checksum_valid(gstin: str | None) -> bool:
    """Validates the GSTIN's trailing checksum digit (mod-36, per GSTN spec)."""
    if not is_well_formed(gstin):
        return False
    gstin = gstin.strip().upper()
    factor = 1
    total = 0
    for ch in gstin[:-1]:
        digit = _CHARSET.index(ch)
        val = digit * factor
        val = (val // 36) + (val % 36)
        total += val
        factor = 2 if factor == 1 else 1
    check_code = _CHARSET[(36 - (total % 36)) % 36]
    return check_code == gstin[-1]


def state_code(gstin: str | None) -> str | None:
    if not gstin or len(gstin) < 2:
        return None
    return gstin[:2]
