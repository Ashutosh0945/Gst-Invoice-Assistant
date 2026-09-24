import tempfile

from backend.extraction.pipeline import extract_invoice
from backend.ingestion.loader import load_document
from backend.synthetic.generate import generate_invoice
from backend.validation.engine import validate_invoice
from backend.schemas import Severity


def _validate(seed, inject_error=None, n_items=3):
    si = generate_invoice(seed=seed, n_items=n_items, inject_error=inject_error)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(si.pdf_bytes)
        tmp.flush()
        _, pages = load_document(tmp.name)
        inv, _ = extract_invoice(pages)
    return validate_invoice(inv)


def test_clean_invoice_has_no_errors():
    findings = _validate(seed=10, inject_error=None)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert errors == []


def test_arithmetic_error_detected():
    findings = _validate(seed=11, inject_error="arithmetic")
    codes = {f.code for f in findings}
    assert "LINE_ARITHMETIC_MISMATCH" in codes


def test_gst_rate_mismatch_detected():
    findings = _validate(seed=12, inject_error="gst_rate")
    codes = {f.code for f in findings}
    assert "LINE_GST_MISMATCH" in codes or "HSN_RATE_MISMATCH" in codes


def test_invalid_hsn_format_flagged_when_present():
    # A malformed HSN that the regex row-matcher can still capture (letters
    # confined to a still-parseable position) should be flagged directly.
    from backend.schemas import InvoiceData, LineItem
    from decimal import Decimal
    import datetime

    inv = InvoiceData(
        vendor_gstin="27AAAAA1111A1Z2", buyer_gstin="27BBBBB2222B1Z5",
        invoice_number="X1", invoice_date=datetime.date.today(),
        items=[LineItem(line_no=1, hsn_sac="12A4", quantity=Decimal(1), unit_price=Decimal(100),
                        taxable_value=Decimal(100), gst_rate=Decimal(18),
                        cgst=Decimal(9), sgst=Decimal(9), line_total=Decimal(118))],
        subtotal=Decimal(100), total_cgst=Decimal(9), total_sgst=Decimal(9),
        grand_total=Decimal(118),
    )
    findings = validate_invoice(inv)
    assert any(f.code == "HSN_INVALID_FORMAT" for f in findings)


def test_tax_type_conflict_same_state_charged_igst():
    from backend.schemas import InvoiceData, LineItem
    from decimal import Decimal
    import datetime

    inv = InvoiceData(
        vendor_gstin="27AAAAA1111A1Z2", buyer_gstin="27BBBBB2222B1Z5",  # same state 27
        invoice_number="X2", invoice_date=datetime.date.today(),
        items=[LineItem(line_no=1, hsn_sac="1006", quantity=Decimal(1), unit_price=Decimal(100),
                        taxable_value=Decimal(100), gst_rate=Decimal(5), igst=Decimal(5),
                        line_total=Decimal(105))],
        subtotal=Decimal(100), total_igst=Decimal(5), grand_total=Decimal(105),
    )
    findings = validate_invoice(inv)
    codes = {f.code for f in findings}
    assert "TAX_TYPE_WRONG_FOR_SAME_STATE" in codes
