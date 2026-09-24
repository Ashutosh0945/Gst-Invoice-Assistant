"""Field-level accuracy benchmark for every available extractor.

Generates held-out synthetic invoices in two different layouts (the extractor
never sees these seeds during training), runs each extractor, and compares
field by field with the exact ground truth the invoice was rendered from.

    python -m ml.benchmark                       # rules extractors only
    python -m ml.benchmark --model models/layoutlmv3-gst   # also LayoutLMv3
    python -m ml.benchmark --n 100 --out data/benchmarks/results.json

Results are written as JSON; the web app's "Model accuracy" page reads it.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

HEADER_FIELDS = ["vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "subtotal",
                 "total_cgst", "total_sgst", "total_igst", "grand_total"]
ITEM_FIELDS = ["hsn_sac", "quantity", "unit_price", "taxable_value", "gst_rate", "line_total"]
SEED_OFFSET = 900_000   # keeps benchmark seeds disjoint from training seeds (0..N)


def _norm(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v.quantize(Decimal("0.01"))
    if isinstance(v, (int, float)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    s = str(v).strip()
    try:
        return Decimal(s.replace(",", "")).quantize(Decimal("0.01"))
    except Exception:  # noqa: BLE001
        return s.upper()


def _truth_layout_a(seed: int):
    from backend.synthetic.generate import generate_invoice

    si = generate_invoice(seed=seed, n_items=2 + seed % 4)
    gt = si.ground_truth.model_dump()
    return si.pdf_bytes, gt


def _truth_layout_b(seed: int):
    from backend.synthetic.generator import generate

    with tempfile.TemporaryDirectory() as d:
        si = generate(Path(d) / "x.pdf", seed=seed, intra=None if seed % 2 else False)
        return si.pdf_path.read_bytes(), si.truth


LAYOUTS = {"A (portrait)": _truth_layout_a, "B (landscape)": _truth_layout_b}


def _load_pages(pdf: bytes):
    from backend.ingestion.loader import load_document

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf)
        tmp.flush()
        _, pages = load_document(tmp.name)
    return pages


def _extractors(model_path: str | None):
    from backend.extraction.heuristic import extract as heuristic_extract
    from backend.extraction.rules_baseline import extract_baseline
    from backend.schemas import PageData

    def to_pagedata(pages):
        return [PageData(page=p.page_index, width=p.width, height=p.height, source="native",
                         words=p.native_words) for p in pages]

    from backend.extraction.pipeline import extract_rules_ensemble

    ex = {
        "Regex baseline": lambda pages: extract_baseline([w for p in pages for w in p.native_words]),
        "Layout heuristic": lambda pages: heuristic_extract(to_pagedata(pages)),
        "Rules ensemble": lambda pages: extract_rules_ensemble(
            [w for p in pages for w in p.native_words], to_pagedata(pages)),
    }
    if model_path:
        import os

        os.environ["LAYOUTLM_MODEL_PATH"] = model_path
        from backend.config import reset_settings_cache
        from backend.extraction import layoutlm

        reset_settings_cache()
        layoutlm._get_model.cache_clear()
        layoutlm._get_model()   # fail fast if the model can't load
        ex["LayoutLMv3"] = lambda pages: layoutlm.extract_layoutlm(
            pages[0].image, [w for p in pages for w in p.native_words])
    return ex


def evaluate(n: int, model_path: str | None) -> dict:
    extractors = _extractors(model_path)
    results: dict = {}
    docs = {name: [fn(SEED_OFFSET + i) for i in range(n)] for name, fn in LAYOUTS.items()}
    for ex_name, ex in extractors.items():
        per_layout = {}
        for layout, samples in docs.items():
            field_hits = {f: 0 for f in HEADER_FIELDS + ITEM_FIELDS}
            field_totals = {f: 0 for f in HEADER_FIELDS + ITEM_FIELDS}
            item_count_ok, timings, perfect = 0, [], 0
            for pdf, gt in samples:
                pages = _load_pages(pdf)
                t0 = time.perf_counter()
                try:
                    got = ex(pages).model_dump()
                except Exception:  # noqa: BLE001 - a crash counts as all-wrong
                    got = {"items": []}
                timings.append(time.perf_counter() - t0)
                doc_ok = True
                for f in HEADER_FIELDS:
                    exp = _norm(gt.get(f))
                    if exp is None or exp == Decimal("0.00"):
                        continue
                    field_totals[f] += 1
                    if _norm(got.get(f)) == exp:
                        field_hits[f] += 1
                    else:
                        doc_ok = False
                gt_items, got_items = gt.get("items") or [], got.get("items") or []
                if len(gt_items) == len(got_items):
                    item_count_ok += 1
                else:
                    doc_ok = False
                for k, exp_item in enumerate(gt_items):
                    exp_item = exp_item if isinstance(exp_item, dict) else exp_item.model_dump()
                    got_item = got_items[k] if k < len(got_items) else {}
                    for f in ITEM_FIELDS:
                        exp = _norm(exp_item.get(f))
                        if exp is None:
                            continue
                        field_totals[f] += 1
                        if _norm(got_item.get(f)) == exp:
                            field_hits[f] += 1
                        else:
                            doc_ok = False
                perfect += doc_ok
            hits, totals = sum(field_hits.values()), sum(field_totals.values())
            per_layout[layout] = {
                "documents": len(samples),
                "field_accuracy": round(hits / totals, 4) if totals else None,
                "header_accuracy": _ratio(field_hits, field_totals, HEADER_FIELDS),
                "line_item_accuracy": _ratio(field_hits, field_totals, ITEM_FIELDS),
                "item_count_accuracy": round(item_count_ok / len(samples), 4),
                "perfect_documents": round(perfect / len(samples), 4),
                "ms_per_document": round(1000 * statistics.mean(timings), 1),
                "per_field": {f: round(field_hits[f] / field_totals[f], 4)
                              for f in field_hits if field_totals[f]},
            }
        allh = [v["field_accuracy"] for v in per_layout.values() if v["field_accuracy"] is not None]
        results[ex_name] = {"overall_field_accuracy": round(statistics.mean(allh), 4) if allh else None,
                            "layouts": per_layout}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents_per_layout": n, "layouts": list(LAYOUTS), "header_fields": HEADER_FIELDS,
        "item_fields": ITEM_FIELDS, "layoutlm_model": model_path, "extractors": results,
    }


def _ratio(hits, totals, fields):
    h, t = sum(hits[f] for f in fields), sum(totals[f] for f in fields)
    return round(h / t, 4) if t else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=40, help="documents per layout")
    ap.add_argument("--model", default=None, help="path to a fine-tuned LayoutLMv3 checkpoint")
    ap.add_argument("--out", default="data/benchmarks/results.json")
    args = ap.parse_args()
    res = evaluate(args.n, args.model)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2))
    for name, r in res["extractors"].items():
        print(f"{name:18s} overall {r['overall_field_accuracy']:.1%}  " + "  ".join(
            f"{lay}: {v['field_accuracy']:.1%}" for lay, v in r["layouts"].items()))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
