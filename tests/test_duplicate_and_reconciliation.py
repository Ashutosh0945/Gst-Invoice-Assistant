from decimal import Decimal

from backend.db.models import Invoice, PurchaseOrder, POLine, Vendor
from backend.reconciliation.matcher import reconcile_invoice
from backend.schemas import InvoiceData, LineItem, ReconStatus
from backend.validation.duplicate import find_duplicates
import datetime


def test_exact_duplicate_detected(db):
    inv = Invoice(source_filename="a.pdf", document_hash="hash123", invoice_number="INV-1",
                  invoice_date=datetime.date.today(), vendor_gstin_raw="27AAAAA1111A1Z2",
                  grand_total=Decimal("100.00"), status="AUTO_APPROVED")
    db.add(inv)
    db.commit()

    data = InvoiceData(invoice_number="INV-1", vendor_gstin="27AAAAA1111A1Z2", grand_total=Decimal("100.00"))
    findings = find_duplicates(db, "hash123", data)
    assert any(f.code == "DUPLICATE_EXACT_FILE" for f in findings)


def test_fuzzy_duplicate_detected(db):
    inv = Invoice(source_filename="a.pdf", document_hash="hashA", invoice_number="INV-1000",
                  invoice_date=datetime.date(2026, 1, 10), vendor_gstin_raw="27AAAAA1111A1Z2",
                  grand_total=Decimal("500.00"), status="AUTO_APPROVED")
    db.add(inv)
    db.commit()

    data = InvoiceData(invoice_number="INV-1000", vendor_gstin="27AAAAA1111A1Z2",
                        invoice_date=datetime.date(2026, 1, 11), grand_total=Decimal("500.00"))
    findings = find_duplicates(db, "hashB", data)
    assert any(f.code == "DUPLICATE_LIKELY" for f in findings)


def test_no_duplicate_for_different_invoice(db):
    inv = Invoice(source_filename="a.pdf", document_hash="hashA", invoice_number="INV-1000",
                  invoice_date=datetime.date(2026, 1, 10), vendor_gstin_raw="27AAAAA1111A1Z2",
                  grand_total=Decimal("500.00"), status="AUTO_APPROVED")
    db.add(inv)
    db.commit()

    data = InvoiceData(invoice_number="INV-9999", vendor_gstin="27AAAAA1111A1Z2",
                        invoice_date=datetime.date(2026, 6, 1), grand_total=Decimal("50.00"))
    findings = find_duplicates(db, "hashC", data)
    assert findings == []


def test_po_full_match(db):
    vendor = Vendor(gstin="27AAAAA1111A1Z2", name="Test Vendor", normalized_name="test vendor")
    db.add(vendor); db.flush()
    po = PurchaseOrder(po_number="PO-1", vendor_id=vendor.id, status="OPEN")
    db.add(po); db.flush()
    db.add(POLine(po_id=po.id, line_no=1, description="Widget", hsn_sac="8471",
                  quantity=Decimal("10"), unit_price=Decimal("100")))
    db.commit()

    data = InvoiceData(po_number="PO-1", vendor_gstin="27AAAAA1111A1Z2", items=[
        LineItem(line_no=1, description="Widget", hsn_sac="8471", quantity=Decimal("10"), unit_price=Decimal("100")),
    ])
    findings, rows = reconcile_invoice(db, data)
    assert rows[0]["status"] == ReconStatus.MATCHED.value
    assert not any(f.severity.value == "ERROR" for f in findings)


def test_po_quantity_exceeds_flagged(db):
    vendor = Vendor(gstin="27AAAAA1111A1Z2", name="Test Vendor", normalized_name="test vendor")
    db.add(vendor); db.flush()
    po = PurchaseOrder(po_number="PO-2", vendor_id=vendor.id, status="OPEN")
    db.add(po); db.flush()
    db.add(POLine(po_id=po.id, line_no=1, description="Widget", hsn_sac="8471",
                  quantity=Decimal("5"), unit_price=Decimal("100")))
    db.commit()

    data = InvoiceData(po_number="PO-2", items=[
        LineItem(line_no=1, description="Widget", hsn_sac="8471", quantity=Decimal("50"), unit_price=Decimal("100")),
    ])
    findings, rows = reconcile_invoice(db, data)
    assert any(f.code == "PO_QUANTITY_EXCEEDS" for f in findings)


def test_po_not_found(db):
    data = InvoiceData(po_number="PO-DOES-NOT-EXIST", items=[
        LineItem(line_no=1, description="Widget", quantity=Decimal("1"), unit_price=Decimal("1")),
    ])
    findings, rows = reconcile_invoice(db, data)
    assert any(f.code == "PO_NOT_FOUND" for f in findings)
    assert rows[0]["status"] == ReconStatus.PO_NOT_FOUND.value
