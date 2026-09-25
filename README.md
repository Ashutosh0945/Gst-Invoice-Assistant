# GST Desk — AI invoice processing, GSTR-2B reconciliation & ITC control

An end-to-end system for Indian GST purchase invoices. It reads each invoice (PDF or image),
checks it against GST rules, verifies its e-invoice QR signature, matches it to purchase orders
and to the government's **GSTR-2B** statement, and decides how much **input tax credit (ITC)**
can be claimed — with a plain-English reason for every rupee held back.

**Design rule: rules compute, AI explains.** Every number and every decision comes from
deterministic, unit-tested code. The optional LLM only writes a summary of findings that the
rule engine already produced.

## What it does

| Stage | Module | What happens |
|---|---|---|
| Read | `backend/ingestion`, `backend/ocr`, `backend/extraction` | PDF text layer (or PaddleOCR for scans) → fields. Two rule-based extractors run and the more self-consistent result wins; a fine-tuned LayoutLMv3 is used when configured. |
| Validate | `backend/validation` | GSTIN checksum, HSN/SAC rates (GST 2.0 slabs), line and total arithmetic, CGST/SGST vs IGST, dates. |
| E-invoice | `backend/einvoice` | Decodes the signed QR (JWT), verifies the RS256 signature with the portal's public key, compares QR vs printout. Catches edited totals and forged QRs. |
| Duplicates / PO | `backend/validation/duplicate.py`, `backend/reconciliation` | Exact and near duplicates; PO quantity/price/item matching. |
| GSTR-2B | `backend/gstr2b` | Imports the portal JSON; matches by GSTIN + invoice number (typo-tolerant) + amounts + date. Flags *missing in 2B*, *missing in books*, amount/date/number differences. |
| ITC | `backend/itc` | Section 17(5) blocked credits (editable CSV), 16(2)(aa) presence in 2B, Rule 37 180-day payment, 16(4) deadline, reverse charge, e-invoice mismatches, duplicates. Supports the "same line of business" exception. |
| Score & route | `backend/scoring` | Confidence score → auto-approve or human review. |
| Explain | `backend/llm` (optional) | Short summary for the reviewer. Never computes. |
| Web app | `app/`, `components/` (Next.js) | Overview, invoices, review queue, upload, GSTR-2B, ITC, e-invoice, vendor risk, analytics, PO matching, duplicates, model accuracy. |
| ML | `ml/` | Auto-labelled dataset generator, LayoutLMv3 training (+ Colab notebook), accuracy benchmark. |

## Run it locally (about 10 minutes)

You need **Python 3.11+** and **Node.js 20+**.

```bash
# 1. Backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
export DATABASE_URL="sqlite:///./gst.db" PYTHONPATH=.   # Windows PowerShell: $env:DATABASE_URL="sqlite:///./gst.db"; $env:PYTHONPATH="."

python scripts/init_db.py
python scripts/seed_demo_data.py        # 29 demo invoices, 2 months of GSTR-2B, signed e-invoice QRs
uvicorn backend.api.main:app --reload   # API on http://localhost:8000  (docs: /docs)

# 2. Web app (second terminal)
npm install
npm run dev                             # http://localhost:3000
```

The demo seed creates a **demo** e-invoice signing key in `data/samples/demo_einvoice_keys/`,
and `.env.example` already points `EINVOICE_PUBLIC_KEY_PATHS` at it so demo QRs show as *Verified*.
For real e-invoices, replace it with the public key published by the e-invoice portal (NIC).

**Try these in the demo:** open *Overview* → click *Credit at risk*; open invoice `SUN/…-0245`
(printed total edited after the QR was signed); open *GSTR-2B match* → *July* for the typo and
date-difference matches; download `data/samples/gstr2b_*.json` and re-import it on the GSTR-2B page.

### Using your own data
- **Invoices:** *Upload invoice* page, or `python scripts/process_invoice_cli.py file.pdf`.
- **GSTR-2B:** GST portal → Returns Dashboard → pick the month → GSTR-2B → *Download (JSON)* → *Import GSTR-2B*.
- **Your line of business:** set `ITC_SAME_LINE_PREFIXES` in `.env` (e.g. `9964,9966,9985` for a travel business) so credit on services you resell isn't treated as blocked.
- **Blocked-credit rules:** edit `data/itc/blocked_credits.csv`. The bundled list is illustrative — have a CA review it.

## Tests

```bash
DATABASE_URL="sqlite:///:memory:" LLM_ENABLED=false PYTHONPATH=. pytest -q     # 51 tests, no network needed
npx next build                                                               # type-checks the web app
```

## The AI model: train, then benchmark

```bash
python -m ml.benchmark                    # rule-based extractors only (writes data/benchmarks/results.json)
```

Current result on 40 held-out synthetic invoices per layout:

| Extractor | Layout A | Layout B |
|---|---|---|
| Regex baseline | 100% | 30.3% |
| Layout heuristic | 19.9% | 100% |
| Rules ensemble (used by the pipeline) | 100% | 100% |

Each hand-written extractor only works on the layout it was designed for. A new supplier template
needs new rules; a trained layout model is meant to generalise instead. To train it, open
`ml/train_layoutlm_colab.ipynb` in Google Colab (free T4 GPU, ~30–40 min), which runs:

```bash
pip install -r requirements-ml.txt
python -m ml.generate_dataset --n 750                 # 1,500 auto-labelled invoices, two layouts
python -m ml.train_layoutlm --out models/layoutlmv3-gst
python -m ml.benchmark --model models/layoutlmv3-gst  # adds LayoutLMv3 to the Model accuracy page
```

Then set `LAYOUTLM_MODEL_PATH=models/layoutlmv3-gst`. *Honest limitation:* both benchmark layouts are
synthetic, and the training script has not been run in the author's environment. For a stronger report,
add 30–50 of your own invoices (with personal data removed) as a real-world test set.

## Deploy

- **Docker:** `docker compose up --build` → web on :3000, API on :8000, Postgres on :5432, OCR worker.
- **Vercel + Supabase:** the API runs as a Python serverless function (`api/index.py`) and the Next.js
  app on the same deployment. Set `DATABASE_URL` to Supabase's *pooled* connection string (port 6543),
  run `python scripts/init_db.py` once against it, then `vercel`. OCR/LayoutLMv3 need an always-on
  worker host (`Dockerfile.ml`) — they are too large for serverless.
- **Upgrading a v0.1 database:** run `sql/migrations/002_compliance.sql`, then `python scripts/init_db.py`,
  then `POST /api/v1/itc/reassess`.

## Repository layout

```
backend/
  api/            FastAPI app: routes.py (invoices, analytics), routes_compliance.py (2B, ITC, e-invoice, vendors, ML)
  einvoice/       qr.py (decode), verify.py (signature + field comparison), signing.py (demo/test keys only)
  gstr2b/         parser.py (portal JSON), matcher.py (pure matching), service.py (import + persist)
  itc/            rules.py (17(5) CSV), eligibility.py (pure decision), service.py (persist)
  extraction/     rules_baseline.py, heuristic.py, pipeline.py (ensemble), layoutlm.py, assemble.py, labels.py
  validation/  reconciliation/  scoring/  llm/  ingestion/  ocr/  db/  analytics/  etl/  synthetic/
app/, components/, lib/     Next.js web app (soft-UI dark theme, dependency-free SVG charts)
ml/                         generate_dataset.py, train_layoutlm.py, benchmark.py, Colab notebook
data/hsn/hsn_seed.csv       Illustrative HSN/SAC → rate table (GST 2.0; multi-rate SACs as "5|18")
data/itc/blocked_credits.csv  Section 17(5) rules (BLOCKED / REVIEW)
scripts/                    init_db.py, seed_demo_data.py, process_invoice_cli.py
sql/                        analytics views + migrations
tests/                      51 pytest tests
```

## Known limitations

- GSTIN validation is structural (checksum), not a live GSTN lookup.
- GSTR-2B: only the B2B section is reconciled; credit/debit notes and amendments are counted, not matched.
- HSN/SAC and blocked-credit tables are illustrative starting points, not legal advice.
- The vendor risk score uses fixed weights (see `backend/analytics/compliance.py`); calibrate on real data.
- No user accounts/roles yet: the API supports a single shared `API_KEY`.
