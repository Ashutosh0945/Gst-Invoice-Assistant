"""Import a GSTR-2B statement, reconcile it, and persist the outcome."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db.models import Gstr2bImport, Gstr2bRecord, Invoice
from backend.gstr2b.matcher import BookInvoice, reconcile
from backend.gstr2b.parser import TwoBStatement, parse_gstr2b
from backend.services.audit_service import log_action

EXCLUDED_STATUSES = ("REJECTED", "FAILED")
ZERO = Decimal("0")


def _book(inv: Invoice) -> BookInvoice:
    tax = sum((x or ZERO) for x in (inv.total_cgst, inv.total_sgst, inv.total_igst, inv.total_cess))
    return BookInvoice(inv.id, inv.vendor_gstin_raw, inv.invoice_number, inv.invoice_date, inv.subtotal, tax)


def import_gstr2b(db: Session, raw: bytes, filename: str) -> Gstr2bImport:
    stmt: TwoBStatement = parse_gstr2b(raw)
    settings = get_settings()

    # Re-importing the same period replaces the previous import.
    old = db.execute(select(Gstr2bImport).where(Gstr2bImport.return_period == stmt.return_period)).scalars().all()
    for imp in old:
        old_ids = [r.id for r in imp.records]
        if old_ids:
            db.execute(update(Invoice).where(Invoice.gstr2b_record_id.in_(old_ids))
                       .values(gstr2b_status=None, gstr2b_record_id=None))
        db.delete(imp)
    db.flush()
    db.execute(update(Invoice).where(Invoice.gstr2b_status == "MISSING_IN_2B",
                                     Invoice.invoice_date >= stmt.period_start,
                                     Invoice.invoice_date <= stmt.period_end)
               .values(gstr2b_status=None))

    # Register invoices eligible to match: not rejected, not already matched to another
    # period, dated inside the lookback window up to the end of this period.
    earliest = stmt.period_start - timedelta(days=settings.gstr2b_lookback_days)
    books_q = select(Invoice).where(
        Invoice.status.not_in(EXCLUDED_STATUSES),
        Invoice.invoice_date >= earliest,
        Invoice.invoice_date <= stmt.period_end,
        (Invoice.gstr2b_status.is_(None)) | (Invoice.gstr2b_status == "MISSING_IN_2B"),
    )
    from backend.itc.service import is_possible_duplicate

    book_invoices = [i for i in db.execute(books_q).scalars().all()
                     if i.status == "APPROVED" or not is_possible_duplicate(i)]
    by_id = {i.id: i for i in book_invoices}

    results, missing = reconcile(
        stmt.invoices, [_book(i) for i in book_invoices],
        period_start=stmt.period_start, period_end=stmt.period_end,
        amount_tolerance=settings.gstr2b_amount_tolerance, fuzzy_threshold=settings.gstr2b_fuzzy_threshold,
    )

    imp = Gstr2bImport(return_period=stmt.return_period, gstin=stmt.gstin, source_filename=filename,
                       generated_on=stmt.generated_on, record_count=len(stmt.invoices))
    db.add(imp)
    db.flush()

    for t, res in zip(stmt.invoices, results):
        rec = Gstr2bRecord(
            import_id=imp.id, supplier_gstin=t.supplier_gstin, supplier_name=t.supplier_name,
            invoice_number=t.invoice_number, invoice_date=t.invoice_date, invoice_value=t.invoice_value,
            taxable_value=t.taxable_value, igst=t.igst, cgst=t.cgst, sgst=t.sgst, cess=t.cess,
            place_of_supply=t.place_of_supply, reverse_charge=t.reverse_charge, itc_available=t.itc_available,
            itc_unavailable_reason=t.itc_unavailable_reason, supplier_filed_on=t.supplier_filed_on, irn=t.irn,
            match_status=res.status, matched_invoice_id=res.book_id, match_score=res.score, match_notes=res.notes,
        )
        db.add(rec)
        db.flush()
        if res.book_id is not None:
            inv = by_id[res.book_id]
            inv.gstr2b_status = "IN_2B"
            inv.gstr2b_record_id = rec.id
    for inv_id in missing:
        by_id[inv_id].gstr2b_status = "MISSING_IN_2B"

    log_action(db, None, actor="system", action="GSTR2B_IMPORTED", details={
        "return_period": stmt.return_period, "records": len(stmt.invoices), "missing_in_2b": len(missing),
        "skipped_sections": stmt.skipped_sections,
    })
    db.flush()

    # ITC depends on 2B presence, so re-assess everything the import touched.
    from backend.itc.service import assess_invoices
    assess_invoices(db, list(by_id.values()))
    db.commit()
    db.refresh(imp)
    return imp


def delete_import(db: Session, import_id) -> None:
    imp = db.get(Gstr2bImport, import_id)
    if imp is None:
        return
    ids = [r.id for r in imp.records]
    affected = db.execute(select(Invoice).where(Invoice.gstr2b_record_id.in_(ids))).scalars().all() if ids else []
    for inv in affected:
        inv.gstr2b_status, inv.gstr2b_record_id = None, None
    period_missing = db.execute(select(Invoice).where(
        Invoice.gstr2b_status == "MISSING_IN_2B")).scalars().all()
    for inv in period_missing:
        pe = imp.return_period
        if inv.invoice_date and inv.invoice_date.month == int(pe[:2]) and inv.invoice_date.year == int(pe[2:]):
            inv.gstr2b_status = None
            affected.append(inv)
    db.execute(delete(Gstr2bRecord).where(Gstr2bRecord.import_id == imp.id))
    db.delete(imp)
    db.flush()
    from backend.itc.service import assess_invoices
    assess_invoices(db, affected)
    db.commit()
