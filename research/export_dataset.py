"""Export GSTInvoice-Synth for release / for LayoutLMv3 training.
    python -m research.export_dataset --out gstinvoice-synth --docs-per-layout 40 [--images]
Writes one JSON per document: words, boxes (0-1000 normalised), BIO labels, layout id, ground truth; optional PNG.
Split: layouts 0-15 train, 16-23 unseen-layout test, 24-47 extended (v2) layouts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research.gst_synth import generate


def norm_box(b, w, h):
    return [max(0, min(1000, int(1000 * v / s))) for v, s in zip(b, (w, h, w, h))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gstinvoice-synth")
    ap.add_argument("--docs-per-layout", type=int, default=40)
    ap.add_argument("--layouts", type=int, default=48)
    ap.add_argument("--images", action="store_true", help="also render PNG pages (needed for LayoutLMv3)")
    a = ap.parse_args()
    out = Path(a.out)
    for lid in range(a.layouts):
        split = "train" if lid < 16 else "test_unseen" if lid < 24 else "extended"
        d_out = out / split
        d_out.mkdir(parents=True, exist_ok=True)
        for s in range(a.docs_per_layout):
            d = generate(lid, s)
            name = f"L{lid:02d}_{s:04d}"
            rec = {"id": name, "layout": lid, "width": d.width, "height": d.height, "words": [w for w, _ in d.words],
                   "boxes": [norm_box(b, d.width, d.height) for _, b in d.words], "labels": d.labels,
                   "ground_truth": json.loads(json.dumps(d.truth, default=str))}
            if a.images:
                import pymupdf
                pymupdf.open(stream=d.pdf)[0].get_pixmap(dpi=120).save(str(d_out / f"{name}.png"))
                rec["image"] = f"{name}.png"
            (d_out / f"{name}.json").write_text(json.dumps(rec))
    print(f"wrote {a.layouts * a.docs_per_layout} documents to {out}")


if __name__ == "__main__":
    main()
