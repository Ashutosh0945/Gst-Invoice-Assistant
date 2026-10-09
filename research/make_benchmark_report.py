"""Builds research/BENCHMARK_REPORT.md from research/results/*.json (numbers are never typed by hand)."""
import json
from pathlib import Path

import numpy as np

R = Path(__file__).parent / "results"


def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def main():
    b = json.loads((R / "benchmarks_v06.json").read_text())
    e1 = json.loads((R / "e1_main.json").read_text()) if (R / "e1_main.json").exists() else None
    from research.benchmarks_v06 import bench_anomaly
    seeds = [bench_anomaly(seed=s) for s in range(5)]
    L = ["# GST Desk benchmark report (v0.6)", "",
         "> **All data in this report is SYNTHETIC, generated with known ground truth.** It measures how the algorithms behave on",
         "> controlled cases. It is **not** real-world accuracy. Real-world numbers require the labelled data listed at the end.", "",
         "Reproduce: `python -m research.benchmarks_v06 && python -m research.make_benchmark_report`", ""]
    # extraction
    L += ["## 1. Invoice extraction (research/RESULTS.md, E1/E8/E10)", ""]
    if e1:
        L += ["| Extractor (unseen synthetic layouts) | Header fields | Line items | All fields | Fully correct invoices |", "|---|---|---|---|---|"]
        for n, v in e1["unseen"].items():
            L.append(f"| {n} | {pct(v['header_acc'])} | {pct(v['item_acc'])} | {pct(v['field_acc'])} | {pct(v['perfect_docs'])} |")
    L += ["", "Per-field accuracy (invoice number, GSTIN, date, taxable value, tax, total) is in `results/e1_main.json` → `per_field`.",
          "Manual-review rate in the app = share of invoices with status NEEDS_REVIEW (shown on the dashboard).", ""]
    rc = b["reconciliation"]
    L += ["## 2. GSTR-2B reconciliation", "", f"{rc['records']} GSTR-2B lines vs {rc['register_invoices']} register invoices. Case mix: " +
          ", ".join(f"{k} {v}" for k, v in sorted(rc["mix"].items())) + ", plus 5 deliberately ambiguous lines.", "",
          "| Method | Precision | Recall | False-match rate | Unmatched rate | Manual-review rate | Ambiguous → review |", "|---|---|---|---|---|---|---|"]
    for name, k in (("GST Desk matcher (v0.6)", "ours"), ("Baseline: exact number + GSTIN", "baseline_exact_number")):
        v = rc[k]
        L.append(f"| {name} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['false_match_rate'])} | {pct(v['unmatched_rate'])} | "
                 f"{pct(v['manual_review_rate'])} | {v['ambiguous_sent_to_review']}/{v['ambiguous_cases']} |")
    L += ["", "Caveat: the variations (format changes, one-character typos, date shifts, tax differences) are the kinds the matcher was designed for, so perfect scores here show it works as designed, not that real statements are this clean.", ""]
    d = b["duplicates"]
    L += ["## 3. Duplicate detection", "", f"{d['pairs']} invoice pairs, {d['true_duplicates']} true duplicates.", "",
          "| Method | Precision | Recall | False-positive rate | False-negative rate | Flagged for review |", "|---|---|---|---|---|---|"]
    for name, k in (("Similarity scoring (v0.6)", "ours"), ("Baseline: exact number + GSTIN", "baseline_exact_number")):
        v = d[k]
        L.append(f"| {name} | {pct(v['precision'])} | {pct(v['recall'])} | {pct(v['false_positive_rate'])} | {pct(v['false_negative_rate'])} | {v['flagged_for_review']} |")
    L += ["", "Flag rate by case (ours): " + ", ".join(f"{k} {v}" for k, v in d["ours"]["flag_rate_by_case"].items()) +
          ". Recurring invoices (next number in sequence, same amount) are deliberately never flagged.", "",
          "No supervised duplicate classifier was trained: there are no real labelled duplicate pairs, and training on invented labels would be misleading.", ""]
    L += ["## 4. Anomaly detection (5 seeds, mean ± sd)", "",
          f"Each run: {seeds[0]['invoices']} invoices from 30 vendors, ~6% injected anomalies (amount spikes, wrong tax rate, bursts, unusual combinations). "
          "Review budget = top 7% of invoices.", "",
          "| Method | ROC-AUC | Precision@k | Recall within budget | False-positive rate | Combination anomalies caught |", "|---|---|---|---|---|---|"]
    for name, k in (("Isolation Forest", "isolation_forest"), ("Robust z-score (baseline)", "robust_z_baseline"), ("**Ensemble (used in app)**", "ensemble_max_rank")):
        g = lambda f: [s[k][f] for s in seeds]  # noqa: E731
        combo = [int(s[k]["recall_by_type"]["combination"].split("/")[0]) / max(1, int(s[k]["recall_by_type"]["combination"].split("/")[1])) for s in seeds]
        L.append(f"| {name} | {np.mean(g('roc_auc')):.3f} ± {np.std(g('roc_auc')):.3f} | {np.mean(g('precision_at_k')):.3f} | "
                 f"{np.mean(g('recall_in_review_budget')):.3f} ± {np.std(g('recall_in_review_budget')):.3f} | {np.mean(g('false_positive_rate')):.3f} | {np.mean(combo):.2f} |")
    L += ["", "Why the ensemble: the robust z-score is best for single extreme values; Isolation Forest is best for unusual combinations; "
          "ranking by whichever finds an invoice more unusual was the most accurate and the most stable across seeds. "
          "Scores are not fraud probabilities. With real data, evaluate against reviewer outcomes stored in `anomaly_scores.review_status`.", ""]
    L += ["## 5. Forecasting (MASE, lower is better; < 1 beats in-sample naive)", "", "25 synthetic 24-month series per family; last 3 months held out chronologically.", "",
          "| Model | " + " | ".join(b["forecasting"]["families"]) + " |", "|---|" + "---|" * len(b["forecasting"]["families"])]
    models = list(next(iter(b["forecasting"]["families"].values())))
    for m in models:
        L.append(f"| {m} | " + " | ".join(f"{b['forecasting']['families'][f][m]:.3f}" for f in b["forecasting"]["families"]) + " |")
    L += ["", "The app's selection (rolling-origin over up to 3 past windows; must beat naive by 5%) is the 'selected' row. It is near the best on "
          "trend and seasonal data and close to naive on random walks, where nothing predicts well. MAPE is not used (it breaks near zero).", ""]
    L += ["## What real data is needed for real-world accuracy", "",
          "| Component | Data needed | Minimum to start |", "|---|---|---|",
          "| Extraction | Real invoices with corrected fields (the app already stores corrections in `feedback_records`) | 300–500 invoices from 50+ vendors, split by vendor |",
          "| Reconciliation | Real GSTR-2B files + your register, with reviewer-confirmed matches | 3 months of returns |",
          "| Duplicates | Reviewer decisions on candidates (`duplicate_candidates.status`) | 100+ decided pairs |",
          "| Anomaly | Reviewer outcomes on flags (`anomaly_scores.review_status`) | 200+ reviewed flags |",
          "| Forecasting | Real monthly history | 18–24 months |", ""]
    (Path(__file__).parent / "BENCHMARK_REPORT.md").write_text("\n".join(L))
    print("\n".join(L)[:2500])


if __name__ == "__main__":
    main()
