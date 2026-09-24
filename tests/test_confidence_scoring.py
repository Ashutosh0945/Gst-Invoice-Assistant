from backend.schemas import Finding, InvoiceData, Severity, InvoiceStatus
from backend.scoring.confidence import compute_confidence, decide_status


def test_high_confidence_no_findings_auto_approves():
    inv = InvoiceData(field_confidence={f: 1.0 for f in
                       ["vendor_gstin", "invoice_number", "invoice_date", "grand_total", "subtotal", "items"]})
    conf = compute_confidence(inv, [])
    assert conf >= 0.9
    assert decide_status(conf, []) == InvoiceStatus.AUTO_APPROVED


def test_error_finding_forces_review_even_with_high_confidence():
    inv = InvoiceData(field_confidence={f: 1.0 for f in
                       ["vendor_gstin", "invoice_number", "invoice_date", "grand_total", "subtotal", "items"]})
    findings = [Finding(code="X", severity=Severity.ERROR, category="validation", message="bad")]
    conf = compute_confidence(inv, findings)
    assert decide_status(conf, findings) == InvoiceStatus.NEEDS_REVIEW


def test_low_extraction_confidence_forces_review():
    inv = InvoiceData(field_confidence={f: 0.3 for f in
                       ["vendor_gstin", "invoice_number", "invoice_date", "grand_total", "subtotal", "items"]})
    conf = compute_confidence(inv, [])
    assert decide_status(conf, []) == InvoiceStatus.NEEDS_REVIEW
