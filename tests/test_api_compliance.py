import json
from datetime import date, timedelta

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.synthetic.generator import generate

KEY = {"X-API-Key": "test-console-key"}


def test_upload_2b_and_read_itc(db, tmp_path):
    client = TestClient(app, headers=KEY)
    d = date.today().replace(day=1) - timedelta(days=20)
    si = generate(tmp_path / "a.pdf", seed=3, invoice_date=d, invoice_number="ZX/1001")
    with open(si.pdf_path, "rb") as f:
        r = client.post("/api/v1/invoices", files={"file": ("a.pdf", f, "application/pdf")})
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["itc"]["status"] == "AWAITING_2B"
    assert inv["einvoice_status"] == "NO_QR"

    t = si.truth
    tax = sum(float(i["cgst"] or 0) + float(i["sgst"] or 0) + float(i["igst"] or 0) for i in t["items"])
    doc = {"data": {"rtnprd": d.strftime("%m%Y"), "gstin": t["buyer_gstin"], "docdata": {"b2b": [{
        "ctin": t["vendor_gstin"], "trdnm": "V", "inv": [{"inum": "ZX/1001", "dt": d.strftime("%d-%m-%Y"),
            "val": float(t["grand_total"]), "itcavl": "Y", "rev": "N",
            "items": [{"txval": float(t["subtotal"]), "cgst": tax / 2, "sgst": tax / 2, "igst": 0}]}]}]}}}
    doc["data"]["docdata"]["b2b"][0]["inv"][0]["items"][0].update(
        {"cgst": float(t["total_cgst"] or 0), "sgst": float(t["total_sgst"] or 0), "igst": float(t["total_igst"] or 0)})
    r = client.post("/api/v1/gstr2b/import", files={"file": ("2b.json", json.dumps(doc), "application/json")})
    assert r.status_code == 201, r.text
    assert r.json()["status_counts"] == {"MATCHED": 1}

    detail = client.get(f"/api/v1/invoices/{inv['id']}").json()
    assert detail["gstr2b_status"] == "IN_2B"
    assert detail["itc"]["status"] in ("ELIGIBLE", "NEEDS_REVIEW", "PARTIALLY_ELIGIBLE")

    ov = client.get("/api/v1/compliance/overview").json()
    assert ov["latest_gstr2b"]["return_period"] == d.strftime("%m%Y")
    assert client.get("/api/v1/analytics/vendor-risk").json()[0]["filing_rate"] == 1.0

    r = client.post(f"/api/v1/invoices/{inv['id']}/payment", json={"paid_on": date.today().isoformat()})
    assert r.status_code == 200 and r.json()["payment_date"] == date.today().isoformat()


def test_bad_2b_file_is_a_422(db):
    r = TestClient(app, headers=KEY).post("/api/v1/gstr2b/import", files={"file": ("x.json", "{}", "application/json")})
    assert r.status_code == 422
