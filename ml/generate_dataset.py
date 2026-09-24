"""Build a labelled LayoutLMv3 training set from synthetic invoices.

Every synthetic invoice is rendered from known ground truth, so each word on
the page can be labelled automatically (BIO tags from
backend/extraction/labels.py). Two layouts are mixed so the model learns
what a field *is*, not just where one template happens to put it.

    python -m ml.generate_dataset --n 750 --out data/layoutlm_dataset

Output:
    <out>/images/<id>.png
    <out>/train.jsonl, <out>/val.jsonl  - {"id", "image", "words", "bboxes" (0-1000), "labels"}
    <out>/stats.json                    - label counts, for a sanity check before training
"""
from __future__ import annotations

import argparse
import json
import random
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

import cv2

from backend.extraction.labels import LABELS
from backend.ingestion.loader import load_document

HEADER_KEYS_A = {  # layout A: "Label: value" -> entity for the word(s) after the label
    ("Invoice", "No:"): "INVOICE_NO", ("Date:",): "INVOICE_DATE", ("Vendor", "GSTIN:"): "VENDOR_GSTIN",
    ("Buyer", "GSTIN:"): "BUYER_GSTIN", ("PO", "No:"): "PO_NO", ("Place", "of", "Supply:"): "PLACE_OF_SUPPLY",
    ("Taxable", "Value:"): "SUBTOTAL", ("CGST:",): "TOTAL_CGST", ("SGST:",): "TOTAL_SGST",
    ("IGST:",): "TOTAL_IGST", ("Round", "Off:"): "ROUND_OFF", ("Grand", "Total:"): "GRAND_TOTAL",
}
ITEM_TAIL_A = ["ITEM_HSN", "ITEM_QTY", "ITEM_PRICE", "ITEM_TAXABLE", "ITEM_GSTRATE", "ITEM_TOTAL"]


def _lines(words):
    """Group words into text lines by vertical overlap; each word keeps its original index."""
    order = sorted(range(len(words)), key=lambda i: ((words[i].bbox[1] + words[i].bbox[3]) / 2, words[i].bbox[0]))
    lines: list[list[int]] = []
    for i in order:
        cy = (words[i].bbox[1] + words[i].bbox[3]) / 2
        if lines:
            last = words[lines[-1][0]]
            if abs(cy - (last.bbox[1] + last.bbox[3]) / 2) < 0.5 * (last.bbox[3] - last.bbox[1]):
                lines[-1].append(i)
                continue
        lines.append([i])
    return [sorted(l, key=lambda i: words[i].bbox[0]) for l in lines]


def label_layout_a(words, vendor_name: str | None) -> list[str]:
    labels = ["O"] * len(words)
    lines = _lines(words)
    in_table = False
    for line in lines:
        texts = [words[i].text for i in line]
        if texts and texts[0] == "No" and "HSN" in texts:
            in_table = True
            continue
        if in_table:
            if texts and texts[0].isdigit() and len(texts) >= 8:
                for i in line[1:-6]:
                    labels[i] = ("B-" if i == line[1] else "I-") + "ITEM_DESC"
                for i, ent in zip(line[-6:], ITEM_TAIL_A):
                    labels[i] = "B-" + ent
                continue
            in_table = False
        k = 0
        while k < len(texts):
            for key, ent in HEADER_KEYS_A.items():
                n = len(key)
                if tuple(texts[k:k + n]) == key and k + n < len(texts):
                    labels[line[k + n]] = "B-" + ent
                    if ent == "VENDOR_GSTIN" and vendor_name and "Name:" in texts:
                        j = texts.index("Name:")
                        for m, i in enumerate(line[j + 1:]):
                            labels[i] = ("B-" if m == 0 else "I-") + "VENDOR_NAME"
                    k += n
                    break
            k += 1
    return labels


def _box(b, w, h):
    x0, y0, x1, y1 = b.bbox
    return [max(0, min(1000, int(1000 * x0 / w))), max(0, min(1000, int(1000 * y0 / h))),
            max(0, min(1000, int(1000 * x1 / w))), max(0, min(1000, int(1000 * y1 / h)))]


def make_sample(layout: str, seed: int):
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "inv.pdf"
        if layout == "A":
            from backend.synthetic.generate import generate_invoice

            si = generate_invoice(seed=seed, n_items=1 + seed % 5)
            pdf.write_bytes(si.pdf_bytes)
            _, pages = load_document(pdf)
            page = pages[0]
            labels = label_layout_a(page.native_words, si.ground_truth.vendor_name)
        else:
            from backend.synthetic.generator import generate, label_words

            rng = random.Random(seed)
            si = generate(pdf, seed=seed, intra=rng.random() < 0.6,
                          po_number=f"PO-{rng.randint(100, 999)}" if rng.random() < 0.5 else None)
            _, pages = load_document(pdf)
            page = pages[0]
            scale = page.width / 842.0
            labels = label_words([(w.text, w.bbox) for w in page.native_words], si.cells, scale)
    words = page.native_words
    return page.image, [w.text for w in words], [_box(w, page.width, page.height) for w in words], labels


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=750, help="invoices per layout")
    ap.add_argument("--out", default="data/layoutlm_dataset")
    ap.add_argument("--val-frac", type=float, default=0.1)
    args = ap.parse_args()

    out = Path(args.out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    records, counts = [], Counter()
    for layout in ("A", "B"):
        for seed in range(args.n):
            image, words, boxes, labels = make_sample(layout, seed)
            unknown = set(labels) - set(LABELS)
            if unknown:
                raise ValueError(f"Labels not in the schema: {unknown}")
            sid = f"{layout}{seed:05d}"
            cv2.imwrite(str(out / "images" / f"{sid}.png"), image)
            records.append({"id": sid, "image": f"images/{sid}.png", "words": words, "bboxes": boxes,
                            "labels": labels})
            counts.update(labels)
    random.Random(42).shuffle(records)
    n_val = max(1, int(len(records) * args.val_frac))
    for name, rows in (("val", records[:n_val]), ("train", records[n_val:])):
        with open(out / f"{name}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    (out / "stats.json").write_text(json.dumps({"documents": len(records), "label_counts": dict(counts)}, indent=2))
    print(f"Wrote {len(records) - n_val} train / {n_val} val documents to {out}")
    print("Most common entity labels:", [(k, v) for k, v in counts.most_common(12) if k != "O"])


if __name__ == "__main__":
    main()
