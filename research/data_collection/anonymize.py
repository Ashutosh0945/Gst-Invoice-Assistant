"""Anonymise real invoices BEFORE they are labelled or shared.

Text level (labelled JSON from export_dataset/labelstudio_to_kie): replaces GSTINs (keeping the state code,
with a valid checksum), PAN, phone numbers, e-mails, bank account numbers, IFSC codes and words labelled
VENDOR_NAME / buyer name with consistent fake values (the same real value always maps to the same fake one).
Image level: blacks out the boxes of every replaced word so the picture can't leak them either.

    python -m research.data_collection.anonymize in_dir out_dir
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
PHONE = re.compile(r"(\+91[\s-]?)?\b[6-9]\d{4}\s?\d{5}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
ACCOUNT = re.compile(r"\b\d{9,18}\b")
IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
FAKE_NAMES = ["Alpha Traders", "Beta Supplies", "Gamma Enterprises", "Delta Distributors", "Sigma Industries", "Omega Retail"]


def _rng(value: str) -> random.Random:
    return random.Random(int(hashlib.sha256(value.encode()).hexdigest()[:12], 16))


def fake_gstin(real: str) -> str:
    from backend.validation.gst import gstin_checksum
    r = _rng(real)
    body = real[:2] + "".join(r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(5)) + f"{r.randint(0, 9999):04d}" + \
        r.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + "1Z"
    return body + gstin_checksum(body)


def anonymise_text(t: str) -> tuple[str, bool]:
    o = t
    t = GSTIN.sub(lambda m: fake_gstin(m.group()), t)
    t = PAN.sub(lambda m: "AAAPA" + f"{_rng(m.group()).randint(0, 9999):04d}" + "A", t)
    t = EMAIL.sub("contact@example.com", t)
    t = IFSC.sub("ABCD0000000", t)
    t = PHONE.sub("9000000000", t)
    t = ACCOUNT.sub(lambda m: "X" * len(m.group()) if len(m.group()) >= 11 else m.group(), t)
    return t, t != o


def anonymise_record(rec: dict) -> tuple[dict, list[int]]:
    words, labels = list(rec["words"]), rec["labels"]
    changed = []
    name_words = [i for i, l in enumerate(labels) if l.endswith("VENDOR_NAME") or l.endswith("BUYER_NAME")]
    if name_words:
        fake = _rng(" ".join(words[i] for i in name_words)).choice(FAKE_NAMES).split()
        for k, i in enumerate(name_words):
            words[i] = fake[k] if k < len(fake) else ""
            changed.append(i)
    for i, w in enumerate(words):
        nw, ch = anonymise_text(w)
        if ch:
            words[i] = nw
            changed.append(i)
    out = dict(rec, words=words, anonymised=True)
    out.pop("ground_truth", None)          # rebuild ground truth from anonymised words, never ship the original
    return out, sorted(set(changed))


def blackout(image_path: Path, rec: dict, idx: list[int], out_path: Path) -> None:
    import cv2
    img = cv2.imread(str(image_path))
    h, w = img.shape[:2]
    for i in idx:
        x0, y0, x1, y1 = rec["boxes"][i]
        cv2.rectangle(img, (int(x0 * w / 1000) - 2, int(y0 * h / 1000) - 2), (int(x1 * w / 1000) + 2, int(y1 * h / 1000) + 2), (0, 0, 0), -1)
    cv2.imwrite(str(out_path), img)


def main(src: str, dst: str) -> None:
    s, d = Path(src), Path(dst)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in s.glob("*.json"):
        rec, idx = anonymise_record(json.loads(f.read_text()))
        (d / f.name).write_text(json.dumps(rec))
        if rec.get("image") and (s / rec["image"]).exists():
            blackout(s / rec["image"], json.loads(f.read_text()), idx, d / rec["image"])
        n += 1
    print(f"anonymised {n} documents -> {d}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
