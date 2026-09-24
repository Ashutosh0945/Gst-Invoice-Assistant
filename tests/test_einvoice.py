import hashlib
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from backend.config import reset_settings_cache
from backend.einvoice.qr import find_signed_qr
from backend.einvoice.signing import generate_demo_keypair, sign_qr_payload, stamp_qr_on_pdf
from backend.einvoice.verify import EInvoiceStatus, verify_einvoice
from backend.ingestion.loader import load_document
from backend.schemas import InvoiceData
from backend.synthetic.generator import generate


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    generate_demo_keypair(d / "priv.pem", d / "pub.pem")
    generate_demo_keypair(d / "rogue.pem", d / "rogue_pub.pem")
    return d


@pytest.fixture()
def trust(keys, monkeypatch):
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY_PATHS", str(keys / "pub.pem"))
    reset_settings_cache()
    yield
    reset_settings_cache()


INV = InvoiceData(vendor_gstin="27AAPFU0939F1ZV", buyer_gstin="29AAGCB7383J1Z4", invoice_number="INV/2026/0001",
                  invoice_date=date(2026, 3, 12), grand_total=D("11800.00"))


def _payload(**over):
    d = {"SellerGstin": INV.vendor_gstin, "BuyerGstin": INV.buyer_gstin, "DocNo": INV.invoice_number,
         "DocTyp": "INV", "DocDt": "12/03/2026", "TotInvVal": 11800.0, "ItemCnt": 1, "MainHsnCode": "8471",
         "Irn": hashlib.sha256(b"x").hexdigest(), "IrnDt": "2026-03-12 10:00:00"}
    d.update(over)
    return d


def test_verified_when_signed_and_matching(keys, trust):
    res = verify_einvoice(sign_qr_payload(_payload(), keys / "priv.pem"), INV)
    assert res.status == EInvoiceStatus.VERIFIED and res.signature_valid
    assert all(c["match"] for c in res.comparisons)


def test_tampered_total_is_caught(keys, trust):
    res = verify_einvoice(sign_qr_payload(_payload(TotInvVal=6800.0), keys / "priv.pem"), INV)
    assert res.status == EInvoiceStatus.MISMATCH
    assert [f.code for f in res.findings if f.severity == "ERROR"] == ["E014"]


def test_forged_signature_is_caught(keys, trust):
    res = verify_einvoice(sign_qr_payload(_payload(), keys / "rogue.pem"), INV)
    assert res.status == EInvoiceStatus.SIGNATURE_INVALID and "E003" in [f.code for f in res.findings]


def test_unverified_without_a_key(keys, monkeypatch):
    monkeypatch.setenv("EINVOICE_PUBLIC_KEY_PATHS", "")
    reset_settings_cache()
    res = verify_einvoice(sign_qr_payload(_payload(), keys / "priv.pem"), INV)
    assert res.status == EInvoiceStatus.UNVERIFIED
    reset_settings_cache()


def test_no_qr_and_malformed():
    assert verify_einvoice(None, INV).status == EInvoiceStatus.NO_QR
    assert verify_einvoice("eyJhbGciOiJub25lIn0.eyJ4IjoxfQ.", INV).status == EInvoiceStatus.MALFORMED


def test_qr_roundtrip_through_a_rendered_pdf(keys, tmp_path):
    si = generate(tmp_path / "inv.pdf", seed=11)
    token = sign_qr_payload(_payload(), keys / "priv.pem")
    stamp_qr_on_pdf(si.pdf_path, token, (716, 86, 806, 176))
    _, pages = load_document(si.pdf_path)
    assert find_signed_qr([p.image for p in pages]) == token
