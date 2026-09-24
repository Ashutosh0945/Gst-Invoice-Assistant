import tempfile

from backend.services.pipeline_service import process_invoice_file
from backend.synthetic.generate import generate_invoice


def test_process_invoice_file_end_to_end(db):
    si = generate_invoice(seed=99, n_items=2)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(si.pdf_bytes)
        tmp.flush()
        invoice = process_invoice_file(db, tmp.name)

    assert invoice.id is not None
    assert invoice.invoice_number == si.ground_truth.invoice_number
    assert invoice.status in ("AUTO_APPROVED", "NEEDS_REVIEW")
    assert len(invoice.items) == len(si.ground_truth.items)


def test_reprocessing_same_file_flags_duplicate(db):
    si = generate_invoice(seed=100, n_items=1)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(si.pdf_bytes)
        tmp.flush()
        process_invoice_file(db, tmp.name)
        invoice2 = process_invoice_file(db, tmp.name)

    assert any(f.code == "DUPLICATE_EXACT_FILE" for f in invoice2.findings)
