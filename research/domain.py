"""E10: cross-generator (out-of-family) generalisation and few-shot adaptation.

Invoice FAMILIES: 'synth' (GSTInvoice-Synth, 48 layouts), 'A' and 'B' (the app's two original, independently
written generators). A family is a stand-in for "invoices from a different source/software". Protocol:
  zero-shot     train on synth only                      -> test on family T (never seen)
  multi-source  train on synth + the other app family     -> test on T
  few-shot      train on synth + k labelled docs of T     -> test on T (disjoint documents)
  target-only   train on k labelled docs of T only        -> test on T   (is synthetic pre-training worth it?)
Model: LayoutKIE-CRF (same features/training as research/rigor.py). Usage: python -m research.domain A|B|summary
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from research.gst_synth import generate as synth_generate
from research.noise import add_noise
from research.rigor import crf_extract, crf_feats
from research.run_experiments import score

OUT = Path(__file__).parent / "results"
SYNTH_SPEC = [(lid, s) for lid in range(24) for s in range(8)]       # 192 docs, 24 layouts
EVAL_SEEDS = range(950_000, 950_030)                                 # 30 test docs per family
FEW_SEEDS = list(range(960_000, 960_040))                            # few-shot training docs (disjoint from test)
KS = (5, 10, 20, 40)


def _items(truth):
    return {**truth, "items": [i if isinstance(i, dict) else i.model_dump() for i in truth["items"]]}


def doc(family: str, seed: int):
    """-> (words [(text, bbox)], labels, truth, width, height)"""
    if family == "synth":
        d = synth_generate(seed % 48, seed)
        return d.words, d.labels, d.truth, d.width, d.height
    from backend.ingestion.loader import load_document
    with tempfile.TemporaryDirectory() as tdir:
        if family == "A":
            from backend.synthetic.generate import generate_invoice
            from ml.generate_dataset import label_layout_a
            si = generate_invoice(seed=seed, n_items=1 + seed % 5)
            p = Path(tdir) / "a.pdf"; p.write_bytes(si.pdf_bytes)
            _, pages = load_document(p); pg = pages[0]
            labels = label_layout_a(pg.native_words, si.ground_truth.vendor_name)
            truth = si.ground_truth.model_dump()
        else:
            from backend.synthetic.generator import generate as gen_b, label_words
            si = gen_b(Path(tdir) / "b.pdf", seed=seed, intra=None if seed % 2 else False)
            _, pages = load_document(si.pdf_path); pg = pages[0]
            labels = label_words([(w.text, w.bbox) for w in pg.native_words], si.cells, pg.width / 842.0)
            truth = si.truth
    return [(w.text, w.bbox) for w in pg.native_words], labels, _items(truth), pg.width, pg.height


def train(docs, seed=0):
    import sklearn_crfsuite
    X, Y = [], []
    for n, (w, l, _t, W, H) in enumerate(docs):
        w2, l2 = add_noise(w, l, [0.0, 0.05, 0.1, 0.1][n % 4], seed + n, W, H)
        f, order, _ = crf_feats(w2, W, H)
        X.append(f); Y.append([l2[i] for i in order])
    crf = sklearn_crfsuite.CRF(algorithm="lbfgs", c1=0.05, c2=0.01, max_iterations=80, all_possible_transitions=True)
    crf.fit(X, Y)
    return crf


def evaluate(crf, test_docs):
    hit = tot = perfect = 0
    for w, _l, truth, W, H in test_docs:
        h, it = score(crf_extract(crf, w, W, H), truth)
        hit += sum(ok for _, ok in h + it); tot += len(h + it); perfect += all(ok for _, ok in h + it)
    return {"field_acc": round(hit / tot, 4), "perfect_docs": round(perfect / len(test_docs), 4), "n": len(test_docs)}


def run_target(target: str):
    other = "B" if target == "A" else "A"
    t0 = time.time()
    synth = [synth_generate(lid, s) for lid, s in SYNTH_SPEC]
    synth = [(d.words, d.labels, d.truth, d.width, d.height) for d in synth]
    test = [doc(target, s) for s in EVAL_SEEDS]
    few = [doc(target, s) for s in FEW_SEEDS]
    oth = [doc(other, s) for s in FEW_SEEDS]
    res = {"target": target, "test_docs": len(test)}
    res["zero_shot_synth"] = evaluate(train(synth), test)
    res["multi_source_synth+" + other] = evaluate(train(synth + oth), test)
    res["few_shot"] = {k: evaluate(train(synth + few[:k]), test) for k in KS}
    res["target_only"] = {k: evaluate(train(few[:k]), test) for k in KS}
    res["seconds"] = round(time.time() - t0, 1)
    (OUT / f"e10_domain_{target}.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__" and sys.argv[1] in ("A", "B"):
    run_target(sys.argv[1])


# ----------------------------------------------------------------------------- E10b: realistic multi-vendor scenario
# A business labels a few invoices from SOME vendors; the model must read invoices from vendors nobody labelled.
# Target pool: 14 templates never used for pre-training (synth layouts 36-47 + the app's generators A and B).
# Pre-training data: synth layouts 0-23 only. Each split labels 7 templates and tests on the other 7.
POOL = [f"synth:{lid}" for lid in range(36, 48)] + ["A", "B"]
PRE_SPEC = [(lid, s) for lid in range(24) for s in range(8)]


def doc_t(template: str, seed: int):
    if template.startswith("synth:"):
        d = synth_generate(int(template.split(":")[1]), seed)
        return d.words, d.labels, d.truth, d.width, d.height
    return doc(template, seed)


def run_split(split: int):
    import random
    rnd = random.Random(split)
    pool = POOL[:]
    rnd.shuffle(pool)
    labelled, unlabelled = pool[:7], pool[7:]
    t0 = time.time()
    pre = [synth_generate(lid, s) for lid, s in PRE_SPEC]
    pre = [(d.words, d.labels, d.truth, d.width, d.height) for d in pre]
    test_unseen = [doc_t(t, s) for t in unlabelled for s in range(970_000, 970_004)]
    test_seen = [doc_t(t, s) for t in labelled for s in range(970_000, 970_004)]
    pool_docs = {t: [doc_t(t, s) for s in range(980_000, 980_008)] for t in labelled}
    res = {"split": split, "labelled_templates": labelled, "unlabelled_templates": unlabelled,
           "n_test_unseen": len(test_unseen), "n_test_seen": len(test_seen), "by_k": {}}
    m0 = train(pre)
    res["synthetic_only"] = {"unseen_vendors": evaluate(m0, test_unseen), "labelled_vendors": evaluate(m0, test_seen)}
    for per in (1, 2, 4, 8):
        few = [d for t in labelled for d in pool_docs[t][:per]]
        r = {}
        for name, docs in (("synthetic+labelled", pre + few), ("labelled_only", few)):
            m = train(docs)
            r[name] = {"unseen_vendors": evaluate(m, test_unseen), "labelled_vendors": evaluate(m, test_seen)}
        res["by_k"][len(few)] = r
        print(len(few), {n: v["unseen_vendors"]["field_acc"] for n, v in r.items()})
    res["seconds"] = round(time.time() - t0, 1)
    (OUT / f"e10b_vendors_split{split}.json").write_text(json.dumps(res, indent=2))


if __name__ == "__main__" and sys.argv[1] == "split":
    run_split(int(sys.argv[2]))
