# Deploying GST Desk v0.6

Architecture (unchanged): **Vercel** hosts the Next.js website **and** the Python API (`api/index.py`);
**Supabase** (or Neon) provides PostgreSQL. No new services are needed for v0.6.

## 1. Before you deploy (once)
1. Keep your local `.env` file — it is NOT included in the zip (it contains your database password).
2. Vercel → your project → **Settings → Environment Variables** (Production). Required / optional:

| Variable | Required | Value |
|---|---|---|
| `DATABASE_URL` | yes | Supabase *Transaction pooler* URI with your real password (no quotes, no `[YOUR-PASSWORD]`) |
| `SITE_URL` | recommended | `https://<your-project>.vercel.app` |
| `OPENROUTER_API_KEY` | for AI wording | your OpenRouter key (server-side only) |
| `LLM_ENABLED` | for AI wording | `true` |
| `OPENROUTER_MODEL` | optional | model id (defaults in `backend/config.py`) |
| `AI_TIMEOUT_S` | optional | `25` |
| `GOOGLE_VISION_*` | optional | only if you use Google Vision OCR (see README_GOOGLE_VISION_OCR.md) |

## 2. Deploy
```bash
# in your project folder (unzipped v0.6, with your .env copied back in)
git add .
git commit -m "v0.6: investigation workspace, 2B work queue, ML anomaly/duplicates/forecasting"
git push
```
Vercel builds and deploys automatically. Wait for **Ready** in Vercel → Deployments.

## 3. Database changes (automatic)
On first start the API creates the new tables and columns automatically (`backend/db/schema.py`; additions only — nothing is dropped
or altered): `documents`, `upload_receipts`, `investigations`, `investigation_notes`, `duplicate_candidates`, `ml_models`,
`anomaly_scores`, `forecast_runs`, plus new nullable columns on `gstr2b_records` (mismatch fields, candidates, resolution, assignee).
To create them before deploying instead: `DATABASE_URL="<your url>" PYTHONPATH=. python scripts/init_db.py`.

Storage note: v0.6 keeps each uploaded original (and OCR-ready copy) in `documents`. Uploads are ≤ 4 MB; Supabase's free tier
has 500 MB, so watch database size if you upload thousands of photos.

## 4. Check the deployment
1. `https://<site>/api/v1/health` → `"version": "0.6.0 (actions-ml)"`.
2. `https://<site>/status` → website can reach the API; database `"ready": true`.
3. Upload a PDF on **Upload invoice**; open **Investigate** → the original document is shown.
4. **Risk Center → Unusual invoices → Train / retrain** (needs ≥ 20 invoices).
5. **GSTR-2B match** → import a GSTR-2B JSON → **2B work queue**.
6. **Forecast & what-if** → forecasts appear once there are ≥ 8 months of invoices (otherwise an honest message).
7. **Settings → Install app** works on Chrome/Edge/Android; iOS uses *Share → Add to Home Screen*.

## 5. After each new deploy (PWA)
Open tabs show **"A new version of GST Desk is available — Reload"**. Clicking it switches to the new version safely.

## 6. Run tests locally
```bash
pip install -r requirements.txt -r research/requirements.txt
DATABASE_URL="sqlite:///:memory:" LLM_ENABLED=false PYTHONPATH=. python -m pytest -q
npm ci && npx next build                 # includes TypeScript type checks
python -m research.benchmarks_v06 && python -m research.make_benchmark_report    # synthetic benchmarks
```

## 7. Known deployment limits
- Photo OCR needs an OCR engine. Vercel's Python size limit excludes PaddleOCR/RapidOCR; use Google Vision (already supported)
  or run the API on Render/Docker with `requirements-ocr.txt`. PDFs with text work everywhere.
- The ML models train on demand (button / `POST /api/v1/ml/anomaly/train`), never during normal requests; training on a few
  thousand invoices takes seconds within Vercel's 60 s limit. Much larger datasets should be trained locally with the same code.
