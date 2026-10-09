"""Benchmarks for reconciliation, duplicates, anomaly detection and forecasting (Improvement 8).
ALL DATA HERE IS SYNTHETIC with known ground truth; results measure the algorithms, NOT real-world accuracy.
Usage: python -m research.benchmarks_v06  -> research/results/benchmarks_v06.json + research/BENCHMARK_REPORT.md"""
from __future__ import annotations

import json
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent
D = Decimal


# ============================================================================ 1. GSTR-2B reconciliation
def bench_reconciliation(seed=0, n=300):
    from backend.gstr2b.matcher import BookInvoice, reconcile
    from backend.gstr2b.parser import TwoBInvoice
    rng = random.Random(seed)
    gstins = [f"27ABCDE{1000 + k}F1Z{k % 10}" for k in range(20)]
    books, twob, truth = [], [], []       # truth[i] = expected book id for twob[i] (None = no true partner)
    start = date(2026, 8, 1)
    kinds = []
    for k in range(n):
        g = rng.choice(gstins)
        no = f"INV/{rng.randint(1, 9999):04d}"
        d = start + timedelta(days=rng.randint(0, 29))
        tx = D(rng.randint(500, 90000)); tax = (tx * D("0.18")).quantize(D("0.01"))
        kind = rng.choices(["exact", "format", "typo", "date", "tax", "missing_2b", "extra_2b"], [40, 15, 10, 5, 10, 10, 10])[0]
        kinds.append(kind)
        if kind != "extra_2b":
            books.append(BookInvoice(k, g, no, d, tx, tax))
        if kind == "missing_2b":
            continue
        n2, d2, tax2 = no, d, tax
        if kind == "format":
            n2 = no.replace("/", "-").replace("INV-0", "INV-").replace("INV-00", "INV-")
        elif kind == "typo":
            n2 = no[:-1] + str((int(no[-1]) + 1) % 10)
        elif kind == "date":
            d2 = d + timedelta(days=rng.choice([-2, 1, 3]))
        elif kind == "tax":
            tax2 = tax + D(rng.choice([50, 120, 900]))
        elif kind == "extra_2b":
            n2 = f"EXT/{rng.randint(1, 9999)}"
        twob.append(TwoBInvoice(supplier_gstin=g, supplier_name="V", invoice_number=n2, invoice_date=d2, invoice_value=tx + tax2,
                                taxable_value=tx, igst=D(0), cgst=tax2 / 2, sgst=tax2 / 2, cess=D(0), place_of_supply="27",
                                reverse_charge=False, itc_available=True, itc_unavailable_reason=None, supplier_filed_on=None, irn=None))
        truth.append(None if kind == "extra_2b" else k)
    # an ambiguous case: two register invoices with look-alike numbers and identical amounts
    for j in range(5):
        g = gstins[j]; d = start + timedelta(days=10); tx = D(1000); tax = D(180)
        books += [BookInvoice(10_000 + 2 * j, g, f"AMB/0{j}7", d, tx, tax), BookInvoice(10_001 + 2 * j, g, f"AMB/00{j}7", d, tx, tax)]
        twob.append(TwoBInvoice(supplier_gstin=g, supplier_name="V", invoice_number=f"AMB/{j}7", invoice_date=d, invoice_value=tx + tax, taxable_value=tx,
                                igst=D(0), cgst=D(90), sgst=D(90), cess=D(0), place_of_supply="27", reverse_charge=False, itc_available=True,
                                itc_unavailable_reason=None, supplier_filed_on=None, irn=None))
        truth.append("ambiguous")

    def score(results):
        linked = [(r.book_id, t) for r, t in zip(results, truth) if r.book_id is not None]
        correct = sum(1 for b, t in linked if b == t)
        true_pairs = sum(1 for t in truth if isinstance(t, int))
        review = sum(1 for r in results if r.status in ("REVIEW_REQUIRED", "AMOUNT_MISMATCH", "GSTIN_MISMATCH", "POTENTIAL_DUPLICATE"))
        amb = [r for r, t in zip(results, truth) if t == "ambiguous"]
        return {"precision": round(correct / len(linked), 4) if linked else None, "recall": round(correct / true_pairs, 4),
                "false_match_rate": round((len(linked) - correct) / len(results), 4),
                "unmatched_rate": round(sum(1 for r in results if r.book_id is None) / len(results), 4),
                "manual_review_rate": round(review / len(results), 4),
                "ambiguous_sent_to_review": sum(1 for r in amb if r.status == "REVIEW_REQUIRED"), "ambiguous_cases": len(amb)}

    ours, _ = reconcile(twob, books, period_start=start, period_end=start + timedelta(days=30), amount_tolerance=D("1"), fuzzy_threshold=0.8)
    # baseline: exact normalised number + same GSTIN only
    from backend.gstr2b.matcher import normalize_invoice_number as nn
    idx = {}
    for b in books:
        idx.setdefault((b.vendor_gstin, nn(b.invoice_number)), b)
    used, base = set(), []
    for t in twob:
        b = idx.get((t.supplier_gstin, nn(t.invoice_number)))
        ok = b is not None and b.id not in used
        if ok:
            used.add(b.id)
        base.append(type("R", (), {"book_id": b.id if ok else None, "status": "MATCHED" if ok else "MISSING_IN_BOOKS"})())
    return {"records": len(twob), "register_invoices": len(books), "mix": {k: kinds.count(k) for k in set(kinds)},
            "ours": score(ours), "baseline_exact_number": score(base)}


# ============================================================================ 2. duplicate detection
@dataclass
class FakeInv:
    invoice_number: str
    grand_total: Decimal
    invoice_date: date
    document_hash: str
    vendor_gstin_raw: str = "27AAPFU0939F1ZV"
    items: list = field(default_factory=list)

    @property
    def subtotal(self):
        return (self.grand_total / D("1.18")).quantize(D("0.01"))

    @property
    def total_cgst(self):
        return ((self.grand_total - self.subtotal) / 2).quantize(D("0.01"))

    total_sgst = total_cgst
    total_igst = None


def bench_duplicates(seed=0, n=400):
    from backend.ml.duplicates import pair_signals, score_pair
    from backend.gstr2b.matcher import normalize_invoice_number as nn
    rng = random.Random(seed)
    L = lambda t: [type("L", (), {"description": t})()]  # noqa: E731
    pairs = []
    for k in range(n):
        base_no = f"INV/2026/{rng.randint(1, 999):04d}"
        amt = D(rng.randint(1000, 200000)); d = date(2026, 5, 1) + timedelta(days=rng.randint(0, 120)); desc = rng.choice(["Toner", "Cement", "Rent", "Consulting"])
        a = FakeInv(base_no, amt, d, f"h{k}a", items=L(desc))
        kind = rng.choice(["dup_reupload", "dup_format", "dup_ocr", "recurring", "different_amount", "same_number_other_vendor"])
        if kind == "dup_reupload":
            b, y = FakeInv(base_no, amt, d, f"h{k}b", items=L(desc)), 1
        elif kind == "dup_format":
            b, y = FakeInv(base_no.replace("/", "-").replace("-0", "-"), amt, d + timedelta(days=rng.choice([0, 1])), f"h{k}b", items=L(desc)), 1
        elif kind == "dup_ocr":
            b, y = FakeInv(base_no.replace("0", "O", 1), amt, d, f"h{k}b", items=L(desc)), 1
        elif kind == "recurring":
            nxt = f"INV/2026/{int(base_no[-4:]) + 1:04d}"
            b, y = FakeInv(nxt, amt, d + timedelta(days=30), f"h{k}b", items=L(desc)), 0
        elif kind == "different_amount":
            b, y = FakeInv(f"INV/2026/{rng.randint(1000, 1999):04d}", amt * D("1.7"), d + timedelta(days=5), f"h{k}b", items=L(desc)), 0
        else:
            b, y = FakeInv(base_no, amt, d, f"h{k}b", vendor_gstin_raw="29BBBBB1111B1Z5", items=L(desc)), 0
        pairs.append((a, b, y, kind))

    def evaluate(pred):
        tp = sum(1 for p, (_, _, y, _) in zip(pred, pairs) if p and y); fp = sum(1 for p, (_, _, y, _) in zip(pred, pairs) if p and not y)
        fn = sum(1 for p, (_, _, y, _) in zip(pred, pairs) if not p and y); tn = len(pairs) - tp - fp - fn
        by = {}
        for p, (_, _, y, kind) in zip(pred, pairs):
            by.setdefault(kind, [0, 0]); by[kind][0] += int(bool(p)); by[kind][1] += 1
        return {"precision": round(tp / (tp + fp), 4) if tp + fp else None, "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                "false_positive_rate": round(fp / (fp + tn), 4) if fp + tn else None, "false_negative_rate": round(fn / (fn + tp), 4) if fn + tp else None,
                "flagged_for_review": tp + fp, "flag_rate_by_case": {k: f"{a}/{b}" for k, (a, b) in sorted(by.items())}}

    # our scorer only compares invoices of the same vendor (blocking), as in the app
    ours = [(a.vendor_gstin_raw == b.vendor_gstin_raw) and score_pair(pair_signals(a, b))[1] is not None for a, b, _, _ in pairs]
    base = [a.vendor_gstin_raw == b.vendor_gstin_raw and nn(a.invoice_number) == nn(b.invoice_number) for a, b, _, _ in pairs]
    return {"pairs": len(pairs), "true_duplicates": sum(y for _, _, y, _ in pairs), "ours": evaluate(ours), "baseline_exact_number": evaluate(base)}


# ============================================================================ 3. anomaly detection
def bench_anomaly(seed=0, vendors=30, per_vendor=30, rate=0.06):
    from backend.ml import iforest
    from backend.ml.anomaly import _impute, build_features
    rng = np.random.default_rng(seed)
    invs, labels, types = [], [], []
    k = 0
    for v in range(vendors):
        mu = rng.uniform(np.log(2000), np.log(200000)); gst_rate = rng.choice([5, 12, 18, 28])
        d = date(2025, 1, 1) + timedelta(days=int(rng.integers(0, 20)))
        for j in range(per_vendor):
            d = d + timedelta(days=int(rng.integers(8, 16)))
            amt = float(np.exp(rng.normal(mu, 0.25)))
            tax_rate, n_items, kind = gst_rate / 100, int(rng.integers(1, 5)), None
            if j >= 8 and rng.random() < rate:
                kind = rng.choice(["amount_spike", "tax_rate_off", "burst", "combination"])
                if kind == "amount_spike":
                    amt *= rng.choice([8, 12, 20])
                elif kind == "tax_rate_off":
                    tax_rate = rng.choice([0.4, 0.01])
                elif kind == "burst":
                    d = d - timedelta(days=int(rng.integers(8, 15)))     # crammed right after the previous one
                else:   # each feature only mildly unusual, but the COMBINATION is rare: bigger amount + more lines + quick repeat
                    amt *= 2.2; n_items = 6; d = d - timedelta(days=5)
            sub = amt / (1 + tax_rate)
            inv = type("Inv", (), {})()
            inv.id = k; inv.vendor_gstin_raw = f"27V{v:03d}"; inv.vendor_name_raw = f"Vendor {v}"; inv.invoice_date = d
            inv.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=k); inv.grand_total = D(f"{amt:.2f}")
            inv.subtotal = D(f"{sub:.2f}"); inv.total_cgst = inv.total_sgst = D(f"{(amt - sub) / 2:.2f}"); inv.total_igst = inv.total_cess = None
            inv.items = [type("L", (), {"gst_rate": D(str(gst_rate))})() for _ in range(n_items)]; inv.findings = []
            invs.append(inv); labels.append(1 if kind else 0); types.append(kind)
            k += 1
    X, _ = build_features(invs, set())
    med = [float(np.nanmedian(X[:, j])) for j in range(X.shape[1])]
    Xi = _impute(X, med)
    y = np.array(labels)

    def metrics(s):
        order = np.argsort(-s)
        kk = int(y.sum())
        flagged = np.zeros(len(s), bool); flagged[order[: int(0.07 * len(s))]] = True          # review budget: top 7%
        tp = int((flagged & (y == 1)).sum()); fp = int((flagged & (y == 0)).sum())
        pos, neg = s[y == 1], s[y == 0]
        auc = float(np.mean([(p > neg).mean() + 0.5 * (p == neg).mean() for p in pos]))
        by = {t: f"{int(sum(1 for i in range(len(s)) if types[i] == t and flagged[i]))}/{types.count(t)}" for t in ("amount_spike", "tax_rate_off", "burst", "combination")}
        return {"precision_at_k": round(float((y[order[:kk]] == 1).mean()), 4), "precision_in_review_budget": round(tp / max(1, tp + fp), 4),
                "recall_in_review_budget": round(tp / max(1, kk), 4), "false_positive_rate": round(fp / max(1, int((y == 0).sum())), 4),
                "roc_auc": round(auc, 4), "review_workload": int(flagged.sum()), "recall_by_type": by}
    s_if = iforest.score(iforest.fit(Xi, 200, 256, seed), Xi)
    q1, q3 = np.percentile(Xi, 25, axis=0), np.percentile(Xi, 75, axis=0)
    # Fair robust baseline: per-feature robust z (IQR scale; falls back to std, then 1 when a feature is constant),
    # so binary features with zero IQR can't dominate. Score = largest |z| across features.
    sd = Xi.std(axis=0)
    scale = np.where(q3 - q1 > 0, (q3 - q1) / 1.349, np.where(sd > 0, sd, 1.0))
    s_rz = np.max(np.abs((Xi - np.median(Xi, axis=0)) / scale), axis=1)
    rank = lambda v: np.argsort(np.argsort(v)) / (len(v) - 1)  # noqa: E731
    s_ens = np.maximum(rank(s_if), rank(s_rz))                # flag if EITHER method finds it very unusual
    return {"invoices": len(invs), "anomalies": int(y.sum()), "review_budget": "top 7% of invoices",
            "isolation_forest": metrics(s_if), "robust_z_baseline": metrics(s_rz), "ensemble_max_rank": metrics(s_ens)}


# ============================================================================ 4. forecasting
def bench_forecast(seed=0, per_family=25, months=24, h=3):
    from backend.ml.forecasting import MODELS, forecast_series
    rng = np.random.default_rng(seed)
    fams = {}
    for fam in ("trend", "seasonal", "flat_noisy", "random_walk"):
        errs = {m: [] for m in list(MODELS) + ["selected (our procedure)"]}
        for _ in range(per_family):
            t = np.arange(months)
            if fam == "trend":
                y = 100000 + 4000 * t + rng.normal(0, 6000, months)
            elif fam == "seasonal":
                y = 100000 + 30000 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 5000, months)
            elif fam == "flat_noisy":
                y = 100000 + rng.normal(0, 15000, months)
            else:
                y = 100000 + np.cumsum(rng.normal(0, 8000, months))
            y = np.maximum(y, 0)
            train, test = y[:-h], y[-h:]
            scale = np.mean(np.abs(np.diff(train)))
            for m, fn in MODELS.items():
                errs[m].append(np.mean(np.abs(test - fn(train, h))) / scale)
            labels = [f"{2024 + i // 12}-{i % 12 + 1:02d}" for i in range(len(train))]
            sel = forecast_series(labels, train, horizon=h)
            pred = np.array([f["forecast"] for f in sel["forecast"]])
            errs["selected (our procedure)"].append(np.mean(np.abs(test - pred)) / scale)
        fams[fam] = {m: round(float(np.mean(v)), 3) for m, v in errs.items()}
    return {"metric": "MASE on the last 3 months (chronological holdout; < 1 = better than in-sample naive)", "series_per_family": per_family, "families": fams}


def main():
    res = {"note": "SYNTHETIC benchmark data with known ground truth. Not real-world accuracy.",
           "reconciliation": bench_reconciliation(), "duplicates": bench_duplicates(), "anomaly": bench_anomaly(), "forecasting": bench_forecast()}
    (OUT / "results").mkdir(exist_ok=True)
    (OUT / "results" / "benchmarks_v06.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
