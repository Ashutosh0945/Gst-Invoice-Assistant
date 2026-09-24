"""Confidence scoring + human-in-the-loop routing decision.

Combines (a) OCR/extraction field confidence and (b) the severity of
deterministic validation/reconciliation findings into one 0..1 score.
This score, not the LLM, decides whether an invoice needs human review.
"""
from __future__ import annotations

from backend.config import get_settings
from backend.schemas import Finding, InvoiceData, InvoiceStatus, Severity

SEVERITY_PENALTY = {
    Severity.ERROR: 0.25,
    Severity.WARNING: 0.08,
    Severity.INFO: 0.0,
}

REQUIRED_FIELDS = [
    "vendor_gstin", "invoice_number", "invoice_date", "grand_total", "subtotal", "items",
]


def _extraction_score(inv: InvoiceData) -> float:
    if not inv.field_confidence:
        return 0.5
    scores = [inv.field_confidence.get(f, 0.0) for f in REQUIRED_FIELDS if f in inv.field_confidence]
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


def _findings_penalty(findings: list[Finding]) -> float:
    return min(1.0, sum(SEVERITY_PENALTY[f.severity] for f in findings))


def compute_confidence(inv: InvoiceData, findings: list[Finding]) -> float:
    base = _extraction_score(inv)
    penalty = _findings_penalty(findings)
    score = max(0.0, min(1.0, base - penalty))
    return round(score, 4)


def decide_status(confidence: float, findings: list[Finding]) -> InvoiceStatus:
    settings = get_settings()
    has_error = any(f.severity == Severity.ERROR for f in findings)
    if has_error:
        return InvoiceStatus.NEEDS_REVIEW
    if confidence >= settings.auto_approve_threshold:
        return InvoiceStatus.AUTO_APPROVED
    return InvoiceStatus.NEEDS_REVIEW
