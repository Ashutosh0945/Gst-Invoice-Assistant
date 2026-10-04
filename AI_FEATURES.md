# GST Desk v0.4.0 — AI + PWA + interactive UI (final report)

**Principle:** rules and database calculations are the source of truth; AI only words them. Every AI text is
fact-checked in code (`backend/llm/explain.py: unsupported_numbers`): if it contains a number not in the data,
the AI text is discarded and a rule-written answer is shown, labelled as such. AI never writes to the database.

## Features (spec numbering)
| # | Feature | Where | Status |
|---|---|---|---|
| 1 | AI GST Copilot (follow-ups, data cards, source data, copy, clear) | `/copilot`, `POST /api/v1/ai/copilot` | Done |
| 2 | AI CFO Brief (facts vs commentary, regenerate) | Dashboard, `POST /ai/brief` | Done |
| 3 | Existing explanation engine extended (fact-checked) | `backend/llm/explain.py` | Done |
| 4 | Invoice investigation (10 stages, evidence, AI explanation) | `/invoices/{id}/investigate` | Done |
| 5 | Vendor intelligence profile + AI summary + ask Copilot | `/vendors/{gstin}`, `GET /ai/vendors/{key}/profile` | Done |
| 6 | Priority / Risk Center (View → Investigate → Explain) | `/risk`, `GET /ai/risks` | Done |
| 7 | Reconciliation assistant (field-by-field 2B + PO reasons) | `/gstr2b/explain/{id}`, investigate page | Done |
| 8 | Monthly GST report (period/month picker, print, CSV) | `/reports` | Done |
| 9 | Audit report (9 sections, traceable findings) | `/reports` | Done |
| 10 | Natural-language smart search (whitelisted filters, never SQL) | `/invoices`, `POST /ai/search` | Done |
| 11 | Anomaly detection (risk indicators, insufficient history) | `/risk` tab | Done |
| 12 | GST forecasting (linear trend + ~80% range, labelled estimate) | `/forecast`, `GET /ai/forecast` | Done* |
| 13 | What-if simulator (real ITC rules on a copy, nothing saved) | `/forecast`, `POST /ai/whatif` | Done |
| 14 | Human feedback loop (prediction vs correction dataset, metrics ≥20, export, no auto model swap) | upload page, `/settings`, `/ai/feedback/*` | Done |
| 15 | Vendor clarification message (editable, copy, mailto, local draft) | `/invoices/{id}/message` | Done |
| 16 | PWA (manifest, icons, service worker, offline shell, offline queue, sync, retry, duplicate protection, camera, drafts, install, notifications) | `public/`, `lib/offline-queue.ts`, `components/PwaManager.tsx` | Done** |
| 17 | Dark / Light / System theme (tokens, persisted, no flash, reduced motion) | `app/globals.css`, `ThemeToggle` | Done |
| 18 | Command-center dashboard, upload pipeline + preview + confidence + inline corrections, table search/sort/paginate/columns/expand, navigation, states | `app/page.tsx`, `/upload`, `InvoiceTable` | Done*** |

\* GST Desk stores **purchase** invoices only, so the forecast is of GST paid on purchases (input tax), not output liability. Clearly labelled.
\** Notifications are local (shown when the device syncs). Server push to a closed app is NOT implemented: it needs VAPID keys and a push service.
\*** Upload stages after "Uploading" run in one server request, so they're shown as one "processing" step, not live per-stage progress. Document preview is the local file in the same session (files aren't stored server-side).

## v0.5.0 addendum
See CAMERA_AND_SECURITY.md for camera capture optimization and the Security & Compliance Center.

## Database changes
- New table `feedback_records` (created automatically on start by `backend/db/schema.py`). No existing tables changed.
- Not changed: no auth/RLS existed in the project (Supabase is used only as PostgreSQL). Adding user login is a separate decision.

## Environment variables
None new required. Uses `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `LLM_ENABLED`. Optional `AI_TIMEOUT_S` (default 25 s; keeps AI calls inside Vercel's 60 s limit).

## New API routes (`/api/v1/ai/…`)
copilot, brief, kpis, monthly, risks, anomalies, search, investigate/{id}, vendors, vendors/{key}/profile,
reconcile/gstr2b/{id}, reconcile/po/{id}, reports/monthly, reports/audit, forecast, whatif, vendor-message,
feedback/metrics, feedback/export, suggestions.

## Tests
- Python: `tests/test_ai_features.py` (14) + `tests/test_ai_batch2.py` (8) → 87 passed; the same 14 tests that already
  failed in the original project still fail (unrelated, pre-existing).
- Browser (Playwright): PWA 10/10 (manifest, service worker, offline navigation, offline queue, duplicate queue
  prevention, safe retry after server error, exactly-once upload, re-upload confirmation, extracted data, inline
  correction → feedback); UI 12/12 (theme modes + persistence, auto-sync on reconnect, reports, forecast/what-if,
  vendor profile, 2B explain, vendor message, settings, table sorting, mobile layout).
- Regression: 22 pages load, upload works.
- Not tested here: real OpenRouter responses (no key in the test environment; AI path tested with simulated
  responses), live Vercel deployment, real phone camera / install prompt / OS notifications.

## Deploy
`git add . && git commit -m "v0.4.0 AI + PWA" && git push` → Vercel redeploys. Check `/api/v1/health` shows 0.4.0
and `/api/v1/health/llm` is OK. The PWA needs HTTPS (Vercel provides it).
