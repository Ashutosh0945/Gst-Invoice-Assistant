# GST Desk v0.6 — implementation report (11 improvements)

Test results (actually executed in the build environment):
- `pytest`: **122 passed, 14 failed**. The 14 failures are pre-existing and unrelated: `tests/test_personal_app.py` (10) and
  `tests/test_console_security.py` (4) test a personal-user app and a staff-login console that are **not present in this codebase**
  (routes not mounted; `Settings.tax_rules_path` missing). They failed identically before any v0.6 change.
- `next build` (with TypeScript checks): passes, 33 pages.
- Browser end-to-end (Playwright, real API + website): 15/15 workflow checks; 24/24 pages load.
- Two existing GSTR-2B tests were updated because behaviour changed **intentionally**; each still asserts its original invariant
  (one register invoice never matches two 2B lines; a different GSTIN never matches) and now also checks the new status.

| # | Improvement | Status | Notes |
|---|---|---|---|
| 1 | Camera & upload reliability | **Implemented and tested** | Existing OpenCV pipeline kept (HoughLinesP shape fix, fallback to original); added unsupported/empty-file errors, idempotent uploads (`Idempotency-Key` → `upload_receipts`), stored originals + OCR-ready copies (`documents`), Cancel. Duplicate/anomaly checks run after save and can't fail an upload. |
| 2 | Automated tests | **Implemented and tested** | +25 tests (`test_v06_workflows.py`, `test_gstr2b.py` additions); browser E2E scripts. Frontend unit-test framework not added (none existed); covered by build type-checks + Playwright. Auth tests not possible: the app has no user login. |
| 3 | Investigation workspace | **Implemented and tested** | Document viewer, field confidence, findings with rule / expected / actual / difference / next step, 2B, duplicates, ML signal, notes, status, decisions, re-validation (existing validation + ITC code), audit history. |
| 4 | GSTR-2B reconciliation | **Implemented and tested** | Stages A–D: exact; candidates (OSA + RapidFuzz); mismatch fields (taxable vs tax); REVIEW_REQUIRED for ambiguity, GSTIN_MISMATCH, POTENTIAL_DUPLICATE. Work queue (10 categories, assign/resolve), defined metrics. Credit/debit notes & amendments: counted but not reconciled (shown as unsupported). |
| 5 | Evidence-backed Copilot | **Implemented and tested** | Evidence panel (period, sources, definitions, records, provenance, limitations, response categories). New questions: review queue, unresolved by vendor, tax difference, repeated discrepancies, prioritise, forecast. Numbers fact-checked as before. |
| 6 | Dashboard action centre | **Implemented and tested** | Match rate, unresolved mismatches, financial impact (confirmed / potentially affected / requiring review, each defined), transparent priority ranking, recent activity, failed jobs. |
| 7 | PWA & offline sync | **Implemented; partly tested** | Update banner (SW waits for user), idempotent queued uploads, clear-local-data. Offline queue/sync/retry tested earlier and again here. SW update flow and install prompt need manual verification on a real device. |
| 8 | Benchmarks | **Implemented and tested (synthetic only)** | `research/BENCHMARK_REPORT.md` with executed results, definitions, baselines; clearly labelled synthetic; lists the real data needed. |
| 9 | Anomaly intelligence | **Implemented and tested** | Isolation Forest (NumPy, matches scikit-learn: rank corr 0.985) + robust-z baseline; benchmark showed the **ensemble** is best (AUC 0.911±0.007), so production uses it. Prediction-time features only, missing = neutral, versioned model, reproducible scores, review outcomes stored, never blocks processing. |
| 10 | Smart duplicates | **Implemented and tested** | Exact checks kept; near-duplicate similarity (RapidFuzz) with recurring-invoice guard (a real bug was found and fixed by tests); review UI; never deletes/merges. No supervised model (no real labelled pairs). |
| 11 | Predictive analytics | **Implemented and tested** | Naive, seasonal naive, moving average, SES, Holt, linear; rolling-origin evaluation; chosen only if it beats naive by 5%; ~80% intervals; ≥ 8 months required; runs persisted (`forecast_runs`). statsmodels/Prophet not added (size limit; equivalent methods implemented and benchmarked). |

Honest findings worth knowing:
- With a **fair** baseline, robust statistics beat Isolation Forest on single-feature anomalies; Isolation Forest wins on unusual combinations. The ensemble was chosen from this evidence.
- The first forecast-selection design (single holdout) was worse than naive on seasonal data; replaced by rolling-origin selection + seasonal naive.
- All benchmark numbers are synthetic and are **not** real-world accuracy.

Dependencies added: `rapidfuzz` (production, ~3 MB). No new environment variables. Migrations: additive only (see DEPLOYMENT.md).
Manual verification still needed: real phone camera, PWA install/update on devices, live Supabase/Vercel deployment, real OpenRouter responses.
