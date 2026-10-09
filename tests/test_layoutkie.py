"""GST-LayoutKIE: trained model ships with the app, generalises to unseen synthetic layouts, repair is safe,
and adding it never makes the existing rules worse on the original templates."""
import tempfile
from pathlib import Path

from backend.extraction import learned as K
from backend.extraction.pipeline import extract_rules_ensemble
from backend.ingestion.loader import load_document
from backend.schemas import OCRWord, PageData
from research.gst_synth import generate


def test_model_file_ships_and_is_small():
    assert K.is_available() and K.MODEL_PATH.stat().st_size < 5_000_000


def test_reads_unseen_layout_header_fields():
    ok = tot = 0
    for lid in (16, 19, 22):
        for s in (424242, 424243):
            d = generate(lid, s)
            inv = K.extract(d.words, d.width, d.height)
            for f in ("vendor_gstin", "buyer_gstin", "invoice_number", "grand_total"):
                tot += 1
                ok += str(getattr(inv, f)) == str(d.truth[f])
    assert ok / tot >= 0.9


def test_repair_is_safe_on_clean_values_and_fixes_ocr_confusions():
    assert K.repair("GRAND_TOTAL", "1,23,456.00") == "123456.00"
    assert K.repair("GRAND_TOTAL", "l,23,4S6.OO") == "123456.00"
    assert K.repair("SUBTOTAL", "Rs.") == ""                       # currency word is dropped, not mangled
    assert K.repair("VENDOR_GSTIN", "27AAPFUO939FlZV") == "27AAPFU0939F1ZV"
    assert K.repair("INVOICE_NO", "INV/OO1") == "INV/OO1"            # free-text fields untouched
    assert K.repair("ITEM_GSTRATE", "18%") == "18%"


def test_never_makes_original_templates_worse(tmp_path):
    """Regression: the model is a candidate in the rules ensemble but must not win ties on the templates
    the rules were written for (it scored 30-78% there vs 100% for the rules)."""
    from backend.synthetic.generate import generate_invoice
    from backend.synthetic.generator import generate as gen_b
    for pdf, truth in [(generate_invoice(seed=s).pdf_bytes, None) for s in (11, 12)] + \
                      [(gen_b(tmp_path / f"b{s}.pdf", seed=s).pdf_path.read_bytes(), None) for s in (11, 12)]:
        p = tmp_path / "x.pdf"
        p.write_bytes(pdf)
        _, pages = load_document(p)
        p0 = pages[0]
        words = [OCRWord(text=w.text, bbox=w.bbox, conf=1.0) for w in p0.native_words]
        inv = extract_rules_ensemble(words, [PageData(page=0, width=p0.width, height=p0.height, source="native", words=words)])
        assert inv.items and inv.grand_total is not None and inv.subtotal is not None


def test_pipeline_picks_reader_with_consistent_line_taxes(tmp_path):
    """Regression: on an unseen layout a rule reader tied with the model on the old consistency score while
    misreading per-line tax columns, which inflated ITC figures. Line taxes must now add up to header taxes."""
    d = generate(20, 31337)
    p = tmp_path / "x.pdf"
    p.write_bytes(d.pdf)
    _, pages = load_document(p)
    p0 = pages[0]
    words = [OCRWord(text=w.text, bbox=w.bbox, conf=1.0) for w in p0.native_words]
    inv = extract_rules_ensemble(words, [PageData(page=0, width=p0.width, height=p0.height, source="native", words=words)])
    line_tax = sum((li.cgst or 0) + (li.sgst or 0) + (li.igst or 0) for li in inv.items)
    assert abs(float(line_tax) - float(d.truth["total_cgst"] + d.truth["total_sgst"] + d.truth["total_igst"])) < 1
