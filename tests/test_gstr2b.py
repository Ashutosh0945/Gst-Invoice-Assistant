from datetime import date
from decimal import Decimal as D

import pytest

from backend.gstr2b.matcher import BookInvoice, normalize_invoice_number, number_similarity, reconcile
from backend.gstr2b.parser import Gstr2bFormatError, parse_gstr2b

G1, G2 = "27AAPFU0939F1ZV", "29AAGCB7383J1Z4"


def _twob(entries):
    return {"data": {"gstin": "27AAACD1234E1Z5", "rtnprd": "082026", "gendt": "14-09-2026", "docdata": {
        "b2b": [{"ctin": g, "trdnm": "Vendor", "supfildt": "11-09-2026", "inv": invs} for g, invs in entries.items()],
        "cdnr": [{"ctin": G1, "nt": []}]}}}


def _inv(inum, dt, txval, cgst=0, sgst=0, igst=0, itcavl="Y", rsn=""):
    return {"inum": inum, "dt": dt, "val": txval + cgst + sgst + igst, "pos": "27", "rev": "N",
            "itcavl": itcavl, "rsn": rsn,
            "items": [{"num": 1, "rt": 18, "txval": txval, "cgst": cgst, "sgst": sgst, "igst": igst, "cess": 0}]}


def test_parser_reads_portal_shape():
    stmt = parse_gstr2b(_twob({G1: [_inv("INV/1", "05-08-2026", 1000, 90, 90), _inv("INV/2", "06-08-2026", 500,
                                                                                    itcavl="N", rsn="C")]}))
    assert stmt.return_period == "082026"
    assert stmt.period_start == date(2026, 8, 1) and stmt.period_end == date(2026, 8, 31)
    a, b = stmt.invoices
    assert a.invoice_date == date(2026, 8, 5) and a.total_tax == D("180.00")
    assert b.itc_available is False and "16(4)" in b.itc_unavailable_reason
    assert stmt.skipped_sections == {"cdnr": 1}


@pytest.mark.parametrize("bad", ['{"data": {}}', "not json", '{"data": {"rtnprd": "082026", "docdata": {}}}'])
def test_parser_rejects_non_2b_files(bad):
    with pytest.raises(Gstr2bFormatError):
        parse_gstr2b(bad)


def test_invoice_number_normalisation():
    assert normalize_invoice_number("inv/0045") == normalize_invoice_number("INV-45") == "INV45"
    assert number_similarity("NEX/26-0201", "NEX/26-0210") >= 0.85
    assert number_similarity("KA/9981", "KA/9918") >= 0.8        # transposed digits = one edit
    assert number_similarity("A-1", "ZZZ-999") < 0.5


def _books():
    return [
        BookInvoice(1, G1, "INV/1", date(2026, 8, 5), D("1000.00"), D("180.00")),     # exact
        BookInvoice(2, G1, "INV-0002", date(2026, 8, 6), D("500.00"), D("90.00")),    # amount differs in 2B
        BookInvoice(3, G1, "INV/0003", date(2026, 8, 7), D("200.00"), D("36.00")),    # date differs
        BookInvoice(4, G2, "KA/9981", date(2026, 8, 8), D("300.00"), D("54.00")),     # typo in 2B
        BookInvoice(5, G2, "KA/7777", date(2026, 8, 20), D("100.00"), D("18.00")),    # not in 2B
        BookInvoice(6, G2, "KA/1111", date(2026, 7, 20), D("100.00"), D("18.00")),    # earlier period, not in 2B
    ]


def test_reconcile_classifies_every_case():
    stmt = parse_gstr2b(_twob({
        G1: [_inv("INV/1", "05-08-2026", 1000, 90, 90), _inv("INV/2", "06-08-2026", 700, 63, 63),
             _inv("INV/3", "08-08-2026", 200, 18, 18), _inv("INV/99", "09-08-2026", 50, 4.5, 4.5)],
        G2: [_inv("KA/9918", "08-08-2026", 300, igst=54), _inv("KA/7771", "20-08-2026", 999, igst=5)],
    }))
    results, missing = reconcile(stmt.invoices, _books(), period_start=stmt.period_start,
                                 period_end=stmt.period_end, amount_tolerance=D("1"), fuzzy_threshold=0.80)
    got = {stmt.invoices[r.twob_index].invoice_number: (r.status, r.book_id) for r in results}
    assert got["INV/1"] == ("MATCHED", 1)
    assert got["INV/2"] == ("AMOUNT_MISMATCH", 2)
    assert got["INV/3"] == ("DATE_MISMATCH", 3)
    assert got["KA/9918"] == ("FUZZY_MATCHED", 4)
    assert got["INV/99"] == ("MISSING_IN_BOOKS", None)
    assert got["KA/7771"] == ("MISSING_IN_BOOKS", None)   # look-alike number, different amounts -> no pairing
    assert missing == [5]           # book 6 is outside the period, so it is not reported here


def test_one_book_invoice_never_matches_two_2b_lines():
    stmt = parse_gstr2b(_twob({G1: [_inv("INV/1", "05-08-2026", 1000, 90, 90),
                                    _inv("INV-1", "05-08-2026", 1000, 90, 90)]}))
    results, _ = reconcile(stmt.invoices, _books()[:1], period_start=stmt.period_start,
                           period_end=stmt.period_end, amount_tolerance=D("1"), fuzzy_threshold=0.80)
    assert sorted(r.status for r in results) == ["MATCHED", "MISSING_IN_BOOKS"]


def test_different_gstin_never_matches():
    stmt = parse_gstr2b(_twob({G2: [_inv("INV/1", "05-08-2026", 1000, 90, 90)]}))
    results, _ = reconcile(stmt.invoices, _books()[:1], period_start=stmt.period_start,
                           period_end=stmt.period_end, amount_tolerance=D("1"), fuzzy_threshold=0.80)
    assert results[0].status == "MISSING_IN_BOOKS"
