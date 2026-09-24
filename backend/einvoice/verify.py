"""Verify an e-invoice signed QR and compare it with what was printed/extracted.

An e-invoice's QR code is a JWT signed (RS256) by the Invoice Registration
Portal. Its payload carries the seller and buyer GSTIN, document number, date,
total value, item count, main HSN code and the IRN. Because the government
signed it, an edit to the printed invoice (e.g. a changed total) will not
match the QR — that is exactly what this module detects.

Everything here is deterministic. The signature check needs the portal's
public key (EINVOICE_PUBLIC_KEY_PATHS); without one, contents are still
compared but the result is marked UNVERIFIED rather than VERIFIED.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import lru_cache
from pathlib import Path

from backend.config import get_settings
from backend.schemas import Finding, InvoiceData, Severity

IRN_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class EInvoiceStatus(str, Enum):
    VERIFIED = "VERIFIED"                    # signature valid and every field matches
    UNVERIFIED = "UNVERIFIED"                # fields match, but no public key configured to check the signature
    MISMATCH = "MISMATCH"                    # QR is readable but disagrees with the printed invoice
    SIGNATURE_INVALID = "SIGNATURE_INVALID"  # the QR was not signed by any configured key (tampered or fake)
    MALFORMED = "MALFORMED"                  # a QR is present but is not a valid e-invoice JWT
    NO_QR = "NO_QR"                          # no signed QR found (normal for non e-invoices)


@dataclass
class QRPayload:
    header: dict
    claims: dict
    data: dict
    signing_input: bytes
    signature: bytes


@dataclass
class EInvoiceResult:
    status: EInvoiceStatus
    irn: str | None = None
    data: dict | None = None
    signature_checked: bool = False
    signature_valid: bool | None = None
    findings: list[Finding] = field(default_factory=list)
    comparisons: list[dict] = field(default_factory=list)   # [{field, qr, invoice, match}]


class MalformedQR(ValueError):
    pass


def _b64url_decode(part: str) -> bytes:
    padding = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + padding)


def parse_signed_qr(token: str) -> QRPayload:
    try:
        h, p, s = token.strip().split(".")
        header = json.loads(_b64url_decode(h))
        claims = json.loads(_b64url_decode(p))
        signature = _b64url_decode(s)
    except Exception as exc:  # noqa: BLE001
        raise MalformedQR(f"Not a valid JWT: {exc}") from exc
    raw = claims.get("data", claims)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MalformedQR("The 'data' claim is not valid JSON.") from exc
    if not isinstance(raw, dict) or "SellerGstin" not in raw:
        raise MalformedQR("JWT does not contain e-invoice fields (SellerGstin missing).")
    return QRPayload(header, claims, raw, f"{h}.{p}".encode(), signature)


@lru_cache(maxsize=8)
def _load_public_key(path: str):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    pem = Path(path).read_bytes()
    if b"BEGIN CERTIFICATE" in pem:
        from cryptography.x509 import load_pem_x509_certificate

        return load_pem_x509_certificate(pem).public_key()
    return load_pem_public_key(pem)


def verify_signature(payload: QRPayload, key_paths: list[Path]) -> bool:
    """True if any configured key verifies the RS256 signature."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    if payload.header.get("alg") not in ("RS256", None):
        return False
    for path in key_paths:
        try:
            key = _load_public_key(str(path))
            key.verify(payload.signature, payload.signing_input, padding.PKCS1v15(), hashes.SHA256())
            return True
        except InvalidSignature:
            continue
    return False


def _parse_qr_date(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _norm_docno(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v)) if v is not None else None
    except InvalidOperation:
        return None


def _finding(code: str, sev: Severity, msg: str, *, field_: str | None = None,
             expected: str | None = None, actual: str | None = None) -> Finding:
    return Finding(code=code, severity=sev, category="einvoice", message=msg, field=field_,
                   expected=expected, actual=actual)


def verify_einvoice(token: str | None, inv: InvoiceData | None) -> EInvoiceResult:
    """Decode + (optionally) verify a signed QR, and compare it with the extracted invoice."""
    settings = get_settings()
    if not token:
        return EInvoiceResult(EInvoiceStatus.NO_QR, findings=[_finding(
            "E001", Severity.INFO, "No e-invoice QR code found; e-invoice checks skipped.")])

    try:
        payload = parse_signed_qr(token)
    except MalformedQR as exc:
        return EInvoiceResult(EInvoiceStatus.MALFORMED, findings=[_finding(
            "E002", Severity.WARNING, f"A QR code was found but it is not a valid e-invoice QR ({exc}).")])

    d = payload.data
    irn = d.get("Irn")
    result = EInvoiceResult(EInvoiceStatus.UNVERIFIED, irn=irn, data=d)

    if irn and not IRN_RE.match(irn):
        result.findings.append(_finding("E015", Severity.WARNING, "IRN in the QR is not a 64-character hash.",
                                        field_="irn", actual=irn))

    keys = settings.einvoice_key_paths
    if keys:
        result.signature_checked = True
        result.signature_valid = verify_signature(payload, keys)
        if not result.signature_valid:
            result.status = EInvoiceStatus.SIGNATURE_INVALID
            result.findings.append(_finding(
                "E003", Severity.ERROR,
                "The QR code's digital signature does not verify against the e-invoice portal's public key. "
                "The QR may be forged or copied from another document."))
    else:
        result.findings.append(_finding(
            "E004", Severity.INFO,
            "QR decoded, but no portal public key is configured, so the signature was not checked."))

    if inv is not None:
        checks = [
            ("vendor_gstin", "Seller GSTIN", d.get("SellerGstin"), inv.vendor_gstin,
             lambda a, b: (a or "").upper() == (b or "").upper(), "E010"),
            ("buyer_gstin", "Buyer GSTIN", d.get("BuyerGstin"), inv.buyer_gstin,
             lambda a, b: (a or "").upper() == (b or "").upper(), "E011"),
            ("invoice_number", "Invoice number", d.get("DocNo"), inv.invoice_number,
             lambda a, b: _norm_docno(a) == _norm_docno(b), "E012"),
            ("invoice_date", "Invoice date", _parse_qr_date(d.get("DocDt")), inv.invoice_date,
             lambda a, b: a == b, "E013"),
            ("grand_total", "Invoice total", _dec(d.get("TotInvVal")), inv.grand_total,
             lambda a, b: a is not None and b is not None and abs(a - b) <= settings.einvoice_amount_tolerance, "E014"),
        ]
        mismatched = False
        for fld, label, qr_val, inv_val, same, code in checks:
            if qr_val is None or inv_val is None:
                result.comparisons.append({"field": label, "qr": _s(qr_val), "invoice": _s(inv_val), "match": None})
                continue
            ok = bool(same(qr_val, inv_val))
            result.comparisons.append({"field": label, "qr": _s(qr_val), "invoice": _s(inv_val), "match": ok})
            if not ok:
                mismatched = True
                result.findings.append(_finding(
                    code, Severity.ERROR,
                    f"{label} printed on the invoice does not match the government-signed QR code.",
                    field_=fld, expected=_s(qr_val), actual=_s(inv_val)))
        if mismatched and result.status != EInvoiceStatus.SIGNATURE_INVALID:
            result.status = EInvoiceStatus.MISMATCH

    if result.status == EInvoiceStatus.UNVERIFIED and result.signature_checked and result.signature_valid:
        result.status = EInvoiceStatus.VERIFIED
    return result


def _s(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    return str(v)
