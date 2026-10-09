"""Experiments for the GST-LayoutKIE paper. Usage: python -m research.run_experiments e1|e2|e3|e4|e5|final
Results -> research/results/*.json. Figures/tables -> research/make_report.py.

Protocol: 24 synthetic layouts. Layouts 0-15 are TRAINING layouts; 16-23 are NEVER seen in training
(unseen-layout test). Seen-layout test documents use different random seeds from training documents.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

from backend.extraction import learned as K
from backend.extraction.heuristic import extract as heuristic_extract
from backend.extraction.pipeline import extract_rules_ensemble
from backend.extraction.rules_baseline import extract_baseline
from backend.schemas import OCRWord, PageData
from research.gst_synth import generate
from research.noise import add_noise
from research.train_kie import save, train

OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)
TRAIN_L, UNSEEN_L = list(range(16)), list(range(16, 24))
HEADER = ["vendor_gstin", "buyer_gstin", "invoice_number", "invoice_date", "subtotal", "total_cgst", "total_sgst", "total_igst", "grand_total"]
ITEM = ["hsn_sac", "quantity", "unit_price", "taxable_value", "gst_rate", "line_total"]


def norm(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return s.upper()


def score(inv, truth):
    got = inv.model_dump()
    h = [(f, norm(got.get(f)) == norm(truth[f])) for f in HEADER if truth[f] not in (None, 0) and norm(truth[f]) != "0.00"]
    it = []
    gi = got.get("items") or []
    for k, ti in enumerate(truth["items"]):
        g = gi[k] if k < len(gi) else {}
        it += [(f, norm(g.get(f)) == norm(ti[f])) for f in ITEM]
    return h, it


EXTRACTORS = {
    "Regex rules": lambda w, W, H, m: extract_baseline([OCRWord(text=t, bbox=b, conf=1.0) for t, b in w]),
    "Layout heuristic": lambda w, W, H, m: heuristic_extract([PageData(page=0, width=W, height=H, source="native",
                                                               words=[OCRWord(text=t, bbox=b, conf=1.0) for t, b in w])]),
    # use_learned=False: the app's ensemble also consults the production model, which was trained on ALL layouts
    # (including test layouts) -- including it here would leak test data into a baseline.
    "Rules ensemble": lambda w, W, H, m: extract_rules_ensemble([OCRWord(text=t, bbox=b, conf=1.0) for t, b in w],
                                        [PageData(page=0, width=W, height=H, source="native", words=[OCRWord(text=t, bbox=b, conf=1.0) for t, b in w])],
                                        use_learned=False),
    "GST-LayoutKIE (no repair)": lambda w, W, H, m: K.extract(w, W, H, m, repair_values=False),
    "GST-LayoutKIE (ours)": lambda w, W, H, m: K.extract(w, W, H, m),
}


def evaluate(model, layouts, seeds, noise=0.0, names=None):
    names = names or list(EXTRACTORS)
    res = {n: {"h": 0, "ht": 0, "i": 0, "it": 0, "perfect": 0, "docs": 0, "ms": 0.0, "per_field": {}} for n in names}
    for lid in layouts:
        for s in seeds:
            d = generate(lid, s)
            words, _ = add_noise(d.words, d.labels, noise, s + 77, d.width, d.height)
            for n in names:
                t0 = time.perf_counter()
                try:
                    inv = EXTRACTORS[n](words, d.width, d.height, model)
                except Exception:  # noqa: BLE001 - a crash counts as all fields wrong
                    from backend.schemas import InvoiceData
                    inv = InvoiceData()
                r = res[n]
                r["ms"] += (time.perf_counter() - t0) * 1000
                h, it = score(inv, d.truth)
                r["h"] += sum(ok for _, ok in h); r["ht"] += len(h); r["i"] += sum(ok for _, ok in it); r["it"] += len(it)
                r["perfect"] += all(ok for _, ok in h + it); r["docs"] += 1
                for f, ok in h + it:
                    pf = r["per_field"].setdefault(f, [0, 0]); pf[0] += ok; pf[1] += 1
    return {n: {"header_acc": round(r["h"] / r["ht"], 4), "item_acc": round(r["i"] / max(1, r["it"]), 4),
                "field_acc": round((r["h"] + r["i"]) / (r["ht"] + r["it"]), 4), "perfect_docs": round(r["perfect"] / r["docs"], 4),
                "ms_per_doc": round(r["ms"] / r["docs"], 2), "docs": r["docs"],
                "per_field": {f: round(a / b, 4) for f, (a, b) in r["per_field"].items()}} for n, r in res.items()}


def spec(layouts, per_layout, start=0):
    return [(lid, s) for lid in layouts for s in range(start, start + per_layout)]


def dump(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2))
    print(json.dumps(obj, indent=1)[:1500])


def main(exp):
    if exp == "e1":      # main comparison: seen vs unseen layouts, clean input
        model, info = train(spec(TRAIN_L, 40))
        save(model, OUT / "model_e1.npz")
        dump("e1_main", {"train": info, "seen": evaluate(model, TRAIN_L, range(5000, 5006)),
                         "unseen": evaluate(model, UNSEEN_L, range(5000, 5015))})
    elif exp == "e2":    # generalisation vs number of training layouts (fixed 320 training docs)
        out = {}
        for k in (1, 2, 4, 8, 16):
            model, info = train(spec(TRAIN_L[:k], 320 // k))
            out[k] = {"train": info, "unseen": evaluate(model, UNSEEN_L, range(6000, 6008), names=["GST-LayoutKIE (ours)"])["GST-LayoutKIE (ours)"]}
            print(k, out[k]["unseen"]["field_acc"])
        rules = evaluate(None, UNSEEN_L, range(6000, 6008), names=["Regex rules", "Layout heuristic", "Rules ensemble"])
        dump("e2_layouts", {"by_layouts": out, "rules_reference": rules})
    elif exp == "e3":    # robustness to OCR-like noise (unseen layouts)
        z = np.load(OUT / "model_e1.npz")
        model = (z["W"].astype(np.float32), z["b"], [str(c) for c in z["classes"]])
        dump("e3_noise", {str(r): evaluate(model, UNSEEN_L, range(7000, 7008), noise=r) for r in (0.0, 0.05, 0.1, 0.2)})
    elif exp == "e4":    # data efficiency: documents per training layout (16 layouts)
        out = {}
        for n in (2, 5, 10, 20, 40):
            model, info = train(spec(TRAIN_L, n))
            out[n] = {"train": info, "unseen": evaluate(model, UNSEEN_L, range(8000, 8008), names=["GST-LayoutKIE (ours)"])["GST-LayoutKIE (ours)"]}
            print(n, out[n]["unseen"]["field_acc"])
        dump("e4_data", out)
    elif exp == "e5":    # ablation: remove one feature group at a time (unseen layouts)
        import backend.extraction.learned as L
        real_h = L._h
        groups = {"full model": (), "without column header": ("hdr=",), "without left-of-word context": ("l1=", "l2=", "l3=", "L2=", "L3=", "L=NONE", "lsh"),
                  "without position": ("xb=", "yb=", "xyb="), "without word text": ("w=", "p3=", "s3=")}
        out = {}
        for g, drops in groups.items():
            L._h = (lambda s, d=drops: L.N_NUM if d and s.startswith(d) else real_h(s))
            try:
                model, info = train(spec(TRAIN_L, 20))
                out[g] = evaluate(model, UNSEEN_L, range(9000, 9006), names=["GST-LayoutKIE (ours)"])["GST-LayoutKIE (ours)"]
            finally:
                L._h = real_h
            print(g, out[g]["field_acc"])
        dump("e5_ablation", out)
    elif exp == "e6":    # out-of-distribution: invoices from the app's two ORIGINAL generators (never used in training)
        from backend.ingestion.loader import load_document
        import tempfile
        from backend.synthetic.generate import generate_invoice
        from backend.synthetic.generator import generate as gen_b
        res = {}
        for name, make in (("Generator A (portrait)", lambda s: (generate_invoice(seed=s, n_items=2 + s % 4).pdf_bytes,
                                                                  generate_invoice(seed=s, n_items=2 + s % 4).ground_truth.model_dump())),
                           ("Generator B (landscape)", None)):
            hits = {}
            for s in range(900_000, 900_030):
                if make:
                    pdf, truth = make(s)
                else:
                    with tempfile.TemporaryDirectory() as tdir:
                        si = gen_b(Path(tdir) / "x.pdf", seed=s, intra=None if s % 2 else False)
                        pdf, truth = si.pdf_path.read_bytes(), si.truth
                with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                    tmp.write(pdf); tmp.flush(); _, pages = load_document(tmp.name)
                p0 = pages[0]
                words = [(w.text, w.bbox) for w in p0.native_words]
                for n in EXTRACTORS:
                    if n == "GST-LayoutKIE (no repair)":
                        continue
                    inv = EXTRACTORS[n](words, p0.width, p0.height, None)
                    h, it = score(inv, {**truth, "items": [i if isinstance(i, dict) else i.model_dump() for i in truth["items"]]})
                    a = hits.setdefault(n, [0, 0]); a[0] += sum(ok for _, ok in h + it); a[1] += len(h + it)
            res[name] = {n: round(a / b, 4) for n, (a, b) in hits.items()}
            print(name, res[name])
        dump("e6_out_of_distribution", res)
    elif exp == "e7":    # does layout DIVERSITY fix the out-of-distribution gap? (24 vs 48 layouts, same doc count)
        import json as _j
        res = {}
        for name, layouts in (("24 layouts (v1)", list(range(24))), ("48 layouts (v1+v2)", list(range(48)))):
            model, info = train(spec(layouts, 960 // len(layouts)))
            save(model, OUT / f"model_e7_{len(layouts)}.npz")
            res[name] = {"train": info}
        dump("e7_diversity_models", res)
    elif exp == "final":  # production model: all 24 layouts, noise-augmented
        model, info = train(spec(range(48), 20))
        save(model)
        dump("final_model", {"train": info, "layouts": 48, "path": str(K.MODEL_PATH)})


if __name__ == "__main__":
    main(sys.argv[1])
