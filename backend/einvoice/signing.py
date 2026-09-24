"""Create signed e-invoice QR codes for demos and tests ONLY.

Real e-invoice QRs are signed by the government portal with a private key
nobody else has. This module lets the synthetic generator and the test suite
produce QR codes with a locally generated demo key pair, so the verification
path can be exercised end to end. Never use it to make invoices for real use.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def generate_demo_keypair(private_path: Path, public_path: Path) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_path.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))


def sign_qr_payload(data: dict, private_key_path: Path) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({"data": json.dumps(data), "iss": "DEMO-NOT-NIC"}).encode())
    sig = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64(sig)}"


def qr_png(text: str) -> bytes:
    import qrcode

    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=4)
    q.add_data(text)
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image().save(buf, format="PNG")
    return buf.getvalue()


def stamp_qr_on_pdf(pdf_path: Path, token: str, rect: tuple[float, float, float, float] | None = None) -> None:
    """Draws the QR onto page 1 of an existing PDF (top-right corner by default)."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    page = doc[0]
    w = page.rect.width
    r = pymupdf.Rect(*(rect or (w - 150, 20, w - 20, 150)))
    page.insert_image(r, stream=qr_png(token))
    tmp = pdf_path.with_suffix(".tmp.pdf")
    doc.save(str(tmp))
    doc.close()
    tmp.replace(pdf_path)
