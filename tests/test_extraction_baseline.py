import tempfile

from backend.extraction.pipeline import extract_invoice
from backend.ingestion.loader import load_document
from backend.synthetic.generate import generate_invoice


def _extract(seed, **kwargs):
    si = generate_invoice(seed=seed, **kwargs)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(si.pdf_bytes)
        tmp.flush()
        _, pages = load_document(tmp.name)
        inv, sources = extract_invoice(pages)
    return si.ground_truth, inv, sources


def test_extracts_header_fields_correctly():
    gt, inv, sources = _extract(seed=1, n_items=2)
    assert sources == ["native"]
    assert inv.invoice_number == gt.invoice_number
    assert inv.vendor_gstin == gt.vendor_gstin
    assert inv.buyer_gstin == gt.buyer_gstin
    assert inv.grand_total == gt.grand_total
    assert inv.subtotal == gt.subtotal


def test_extracts_line_items():
    gt, inv, _ = _extract(seed=2, n_items=3)
    assert len(inv.items) == len(gt.items)
    for exp, got in zip(gt.items, inv.items):
        assert got.hsn_sac == exp.hsn_sac
        assert got.quantity == exp.quantity
        assert got.taxable_value == exp.taxable_value
