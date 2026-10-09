# GST Desk benchmark report (v0.6)

> **All data in this report is SYNTHETIC, generated with known ground truth.** It measures how the algorithms behave on
> controlled cases. It is **not** real-world accuracy. Real-world numbers require the labelled data listed at the end.

Reproduce: `python -m research.benchmarks_v06 && python -m research.make_benchmark_report`

## 1. Invoice extraction (research/RESULTS.md, E1/E8/E10)

| Extractor (unseen synthetic layouts) | Header fields | Line items | All fields | Fully correct invoices |
|---|---|---|---|---|
| Regex rules | 71.9% | 10.4% | 26.9% | 0.0% |
| Layout heuristic | 67.8% | 35.5% | 44.2% | 0.0% |
| Rules ensemble | 75.0% | 22.7% | 36.7% | 0.0% |
| GST-LayoutKIE (no repair) | 99.5% | 99.9% | 99.8% | 93.3% |
| GST-LayoutKIE (ours) | 99.5% | 99.9% | 99.8% | 93.3% |

Per-field accuracy (invoice number, GSTIN, date, taxable value, tax, total) is in `results/e1_main.json` → `per_field`.
Manual-review rate in the app = share of invoices with status NEEDS_REVIEW (shown on the dashboard).

## 2. GSTR-2B reconciliation

276 GSTR-2B lines vs 278 register invoices. Case mix: date 14, exact 125, extra_2b 32, format 46, missing_2b 29, tax 27, typo 27, plus 5 deliberately ambiguous lines.

| Method | Precision | Recall | False-match rate | Unmatched rate | Manual-review rate | Ambiguous → review |
|---|---|---|---|---|---|---|
| GST Desk matcher (v0.6) | 100.0% | 100.0% | 0.0% | 13.4% | 11.6% | 5/5 |
| Baseline: exact number + GSTIN | 97.7% | 88.7% | 1.8% | 21.4% | 0.0% | 0/5 |

Caveat: the variations (format changes, one-character typos, date shifts, tax differences) are the kinds the matcher was designed for, so perfect scores here show it works as designed, not that real statements are this clean.

## 3. Duplicate detection

400 invoice pairs, 203 true duplicates.

| Method | Precision | Recall | False-positive rate | False-negative rate | Flagged for review |
|---|---|---|---|---|---|
| Similarity scoring (v0.6) | 100.0% | 100.0% | 0.0% | 0.0% | 203 |
| Baseline: exact number + GSTIN | 100.0% | 65.5% | 0.0% | 34.5% | 133 |

Flag rate by case (ours): different_amount 0/61, dup_format 64/64, dup_ocr 70/70, dup_reupload 69/69, recurring 0/62, same_number_other_vendor 0/74. Recurring invoices (next number in sequence, same amount) are deliberately never flagged.

No supervised duplicate classifier was trained: there are no real labelled duplicate pairs, and training on invented labels would be misleading.

## 4. Anomaly detection (5 seeds, mean ± sd)

Each run: 900 invoices from 30 vendors, ~6% injected anomalies (amount spikes, wrong tax rate, bursts, unusual combinations). Review budget = top 7% of invoices.

| Method | ROC-AUC | Precision@k | Recall within budget | False-positive rate | Combination anomalies caught |
|---|---|---|---|---|---|
| Isolation Forest | 0.907 ± 0.021 | 0.479 | 0.596 ± 0.051 | 0.046 | 0.88 |
| Robust z-score (baseline) | 0.870 ± 0.026 | 0.517 | 0.591 ± 0.098 | 0.046 | 0.67 |
| **Ensemble (used in app)** | 0.911 ± 0.007 | 0.572 | 0.645 ± 0.048 | 0.044 | 0.81 |

Why the ensemble: the robust z-score is best for single extreme values; Isolation Forest is best for unusual combinations; ranking by whichever finds an invoice more unusual was the most accurate and the most stable across seeds. Scores are not fraud probabilities. With real data, evaluate against reviewer outcomes stored in `anomaly_scores.review_status`.

## 5. Forecasting (MASE, lower is better; < 1 beats in-sample naive)

25 synthetic 24-month series per family; last 3 months held out chronologically.

| Model | trend | seasonal | flat_noisy | random_walk |
|---|---|---|---|---|
| naive (last month) | 1.243 | 0.697 | 1.142 | 1.382 |
| seasonal naive (same month last year) | 6.603 | 0.468 | 0.948 | 3.665 |
| moving average (3 months) | 1.498 | 1.018 | 0.922 | 1.640 |
| simple exponential smoothing | 1.235 | 0.681 | 0.785 | 1.410 |
| Holt exponential smoothing | 0.934 | 2.300 | 1.257 | 1.511 |
| linear trend | 0.651 | 1.797 | 0.882 | 2.268 |
| selected (our procedure) | 0.749 | 0.468 | 1.012 | 1.458 |

The app's selection (rolling-origin over up to 3 past windows; must beat naive by 5%) is the 'selected' row. It is near the best on trend and seasonal data and close to naive on random walks, where nothing predicts well. MAPE is not used (it breaks near zero).

## What real data is needed for real-world accuracy

| Component | Data needed | Minimum to start |
|---|---|---|
| Extraction | Real invoices with corrected fields (the app already stores corrections in `feedback_records`) | 300–500 invoices from 50+ vendors, split by vendor |
| Reconciliation | Real GSTR-2B files + your register, with reviewer-confirmed matches | 3 months of returns |
| Duplicates | Reviewer decisions on candidates (`duplicate_candidates.status`) | 100+ decided pairs |
| Anomaly | Reviewer outcomes on flags (`anomaly_scores.review_status`) | 200+ reviewed flags |
| Forecasting | Real monthly history | 18–24 months |
