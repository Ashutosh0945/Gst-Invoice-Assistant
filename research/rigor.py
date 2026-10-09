"""E8: multi-seed main comparison with a CRF baseline and statistics.
    python -m research.rigor run <seed>      (one run: fresh train/test data, SGD seed)
    python -m research.rigor aggregate        (mean ± std, bootstrap 95% CI, McNemar tests)
Protocol per run: train on layouts 0-15 (20 docs/layout, data seed = run seed), test on UNSEEN layouts 16-23
(10 docs/layout, disjoint seeds), clean and 5% simulated OCR noise. Per-document outcomes are stored so that
confidence intervals and paired significance tests can be computed."""
from __future__ import annotations

import json
import random
import sys
import time

import numpy as np

from backend.extraction import learned as K
from research.gst_synth import generate
from research.noise import add_noise
from research.run_experiments import EXTRACTORS, OUT, score
from research.train_kie import train

RULES = ["Regex rules", "Layout heuristic", "Rules ensemble"]
OURS, CRF = "GST-LayoutKIE (ours)", "CRF (linear-chain)"


def crf_feats(words, W, H):
    ids, num, lines = K.featurize(words, W, H)
    seq_idx = [i for line in lines for i in line]
    feats = []
    for i in seq_idx:
        d = {f"h{x}": 1.0 for x in ids[i]}
        d.update({f"n{k}": float(num[i, k]) for k in range(K.N_NUM)})
        feats.append(d)
    return feats, seq_idx, lines


def train_crf(spec, seed):
    import sklearn_crfsuite
    X, Y = [], []
    for lid, s in spec:
        d = generate(lid, s)
        rate = [0.0, 0.05, 0.1, 0.1][s % 4]
        w, l = add_noise(d.words, d.labels, rate, s, d.width, d.height)
        f, order, _ = crf_feats(w, d.width, d.height)
        X.append(f); Y.append([l[i] for i in order])
    crf = sklearn_crfsuite.CRF(algorithm="lbfgs", c1=0.05, c2=0.01, max_iterations=80, all_possible_transitions=True)
    crf.fit(X, Y)
    return crf


def export_crf(crf):
    """crfsuite weights -> (W, b, classes, T) in the same hashed layout as the linear model (NumPy inference)."""
    classes = list(crf.classes_)
    ci = {c: k for k, c in enumerate(classes)}
    W = np.zeros((len(classes), K.D), np.float32)
    for (attr, lab), w in crf.state_features_.items():
        col = int(attr[1:]) if attr[0] in "hn" else None
        if col is not None:
            W[ci[lab], col] += w
    T = np.zeros((len(classes), len(classes)), np.float32)
    for (a, b2), w in crf.transition_features_.items():
        T[ci[a], ci[b2]] = w
    return W, np.zeros(len(classes), np.float32), classes, T


def save_crf(model, path):
    W, b, classes, T = model
    np.savez_compressed(path, W=W.astype(np.float16), b=b, classes=np.array(classes), T=T)


def crf_extract(crf, words, W, H):
    f, order, lines = crf_feats(words, W, H)
    pred = crf.predict_marginals_single(f)
    labels, confs = [None] * len(words), [0.0] * len(words)
    for pos, i in enumerate(order):
        lab = max(pred[pos], key=pred[pos].get)
        labels[i], confs[i] = lab, float(pred[pos][lab])
    return K.decode(words, labels, confs, lines)


def run(seed: int):
    t0 = time.time()
    spec = [(lid, seed * 10_000 + s) for lid in range(16) for s in range(20)]
    model, info = train(spec, seed=seed)
    t_lr = time.time() - t0
    crf = train_crf(spec, seed)
    t_crf = time.time() - t0 - t_lr
    if seed == 1:   # keep run-1 models for the real-OCR experiment (trained on layouts 0-15 only)
        from research.train_kie import save
        save(model, OUT / "e9_model_lr.npz"); save_crf(export_crf(crf), OUT / "e9_model_crf.npz")
    out = {"seed": seed, "train_seconds": {"ours": round(t_lr, 1), "crf": round(t_crf, 1)}, "conditions": {}}
    for noise in (0.0, 0.05):
        per = {n: [] for n in RULES + [OURS, CRF]}
        for lid in range(16, 24):
            for s in range(10):
                ts = 500_000 + seed * 10_000 + lid * 100 + s
                d = generate(lid, ts)
                words, _ = add_noise(d.words, d.labels, noise, ts + 1, d.width, d.height)
                for n in per:
                    t = time.perf_counter()
                    inv = crf_extract(crf, words, d.width, d.height) if n == CRF else EXTRACTORS[n](words, d.width, d.height, model)
                    ms = (time.perf_counter() - t) * 1000
                    h, it = score(inv, d.truth)
                    hits = sum(ok for _, ok in h + it)
                    per[n].append({"hits": hits, "total": len(h + it), "perfect": hits == len(h + it), "ms": round(ms, 2)})
        out["conditions"][str(noise)] = per
    (OUT / f"e8_seed{seed}.json").write_text(json.dumps(out))
    for noise, per in out["conditions"].items():
        print("noise", noise, {n: round(sum(x["hits"] for x in v) / sum(x["total"] for x in v), 4) for n, v in per.items()})
    print("train seconds", out["train_seconds"])


def bootstrap_ci(docs, iters=2000, seed=0):
    r = random.Random(seed)
    accs = []
    for _ in range(iters):
        sample = [docs[r.randrange(len(docs))] for _ in docs]
        accs.append(sum(d["hits"] for d in sample) / sum(d["total"] for d in sample))
    return round(float(np.percentile(accs, 2.5)), 4), round(float(np.percentile(accs, 97.5)), 4)


def mcnemar(a, b):
    """Exact two-sided McNemar test on paired binary outcomes (document fully correct)."""
    from scipy.stats import binomtest
    b01 = sum(1 for x, y in zip(a, b) if x and not y)
    b10 = sum(1 for x, y in zip(a, b) if y and not x)
    n = b01 + b10
    return {"ours_only": b01, "other_only": b10, "p_value": float(binomtest(b01, n, 0.5).pvalue) if n else 1.0}


def aggregate():
    runs = [json.loads(p.read_text()) for p in sorted(OUT.glob("e8_seed*.json"))]
    res = {"runs": len(runs), "conditions": {}}
    for cond in runs[0]["conditions"]:
        table = {}
        for n in runs[0]["conditions"][cond]:
            accs = [sum(x["hits"] for x in r["conditions"][cond][n]) / sum(x["total"] for x in r["conditions"][cond][n]) for r in runs]
            perf = [np.mean([x["perfect"] for x in r["conditions"][cond][n]]) for r in runs]
            pooled = [x for r in runs for x in r["conditions"][cond][n]]
            table[n] = {"field_acc_mean": round(float(np.mean(accs)), 4), "field_acc_std": round(float(np.std(accs, ddof=1)) if len(accs) > 1 else 0.0, 4),
                        "field_acc_95ci": bootstrap_ci(pooled), "perfect_mean": round(float(np.mean(perf)), 4),
                        "perfect_std": round(float(np.std(perf, ddof=1)) if len(perf) > 1 else 0.0, 4),
                        "ms_per_doc": round(float(np.mean([x["ms"] for x in pooled])), 2), "docs": len(pooled)}
        ours = [x["perfect"] for r in runs for x in r["conditions"][cond][OURS]]
        tests = {n: mcnemar(ours, [x["perfect"] for r in runs for x in r["conditions"][cond][n]]) for n in table if n != OURS}
        res["conditions"][cond] = {"table": table, "mcnemar_vs_ours": tests}
    res["train_seconds"] = {k: round(float(np.mean([r["train_seconds"][k] for r in runs])), 1) for k in ("ours", "crf")}
    (OUT / "e8_summary.json").write_text(json.dumps(res, indent=2))
    for cond, v in res["conditions"].items():
        print(f"--- noise {cond}")
        for n, t in v["table"].items():
            print(f"{n:24s} {100*t['field_acc_mean']:.1f} ± {100*t['field_acc_std']:.1f}  CI {t['field_acc_95ci']}  perfect {100*t['perfect_mean']:.1f}%  {t['ms_per_doc']} ms")
        print("McNemar (perfect docs) vs ours:", {n: round(t["p_value"], 6) for n, t in v["mcnemar_vs_ours"].items()})
    print("train seconds:", res["train_seconds"])


if __name__ == "__main__":
    run(int(sys.argv[2])) if sys.argv[1] == "run" else aggregate()
