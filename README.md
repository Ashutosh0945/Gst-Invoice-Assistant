# Munshi — your AI accountant, in your pocket

A white-label web app that gives everyday people, shop owners and freelancers the day-to-day help
they would otherwise pay an accountant for:

- **Ask anything about tax.** "Old or new regime?", "Do I need GST registration?", "How much advance
  tax do I pay?", "Who hasn't paid me?" — answered from the user's own data.
- **Snap every bill.** Each bill is read, checked (GST rate, totals, e-invoice QR, duplicates), sorted,
  and kept safe, with warranty reminders and a GST-overcharge detector.
- **Send proper invoices.** GST-correct invoices (CGST/SGST vs IGST decided automatically), PDF download,
  and a clear list of who owes you.
- **Never miss a deadline.** Income tax, advance tax and GST dates, with amounts.

**Design rule: rules compute, AI explains.** The assistant never does tax arithmetic. It calls
deterministic, unit-tested calculators (`backend/personal/tax.py`, driven by
`data/tax/rules_india.json`) and shows which calculator produced each figure. Without an AI key it still
works, answering the supported question types with the same calculators.

> Munshi is an AI assistant, not a chartered accountant. It says so in the app and hands off notices,
> audits, disputes and complex cases to a qualified professional.

## Quick start

See **[HOSTING.md](HOSTING.md)** for step-by-step instructions (local, online, white-labelling). Short version:

```bash
pip install -r requirements.txt && cp .env.example .env
export DATABASE_URL="sqlite:///./gst.db" PYTHONPATH=.
python scripts/init_db.py && python scripts/seed_personal_demo.py
uvicorn backend.api.main:app --reload            # terminal 1
npm install && npm run dev                       # terminal 2 → http://localhost:3000
```
Demo logins (password `demo12345`): `me@demo.in`, `freelancer@demo.in`, `shop@demo.in`.

## What's where

| Area | Files |
|---|---|
| Website pages | `app/page.tsx` (landing), `app/(auth)/` (sign in/up), `app/app/` (home, assistant, bills, invoices, tax, settings) |
| Branding (white-label) | `lib/brand.ts` + `NEXT_PUBLIC_BRAND_*` variables |
| Personal-app API | `backend/api/routes_app.py` (every route scoped to the signed-in user) |
| Accounts & sessions | `backend/personal/auth.py` (PBKDF2 passwords, signed HttpOnly cookie) |
| Tax calculators | `backend/personal/tax.py`, `data/tax/rules_india.json` (FY 2025-26) |
| Assistant | `backend/personal/assistant.py` (tool calling + offline intent router) |
| Bill insights | `backend/personal/bills.py` (overcharges, categories, deduction hints) |
| Invoices you send | `backend/personal/invoicing.py` (GST split, numbering, PDF) |
| Bill reading & checks | `backend/extraction/`, `backend/validation/`, `backend/einvoice/`, `backend/itc/` |
| ML training & benchmark | `ml/` (LayoutLMv3 dataset generator, training script, Colab notebook, benchmark) |
| Staff console (second website) | `console/` — invoice review, GSTR-2B matching, ITC control, e-invoice checks, vendor risk; staff login only (`scripts/create_staff.py`) |

## Tests

```bash
DATABASE_URL="sqlite:///:memory:" LLM_ENABLED=false PYTHONPATH=. pytest -q    # 65 tests
npx next build                                                               # type-checks the website (set BACKEND_URL on Vercel)
```

The personal-app tests cover the tax slabs (87A rebate, marginal relief, deduction caps), GST registration
thresholds, sign-up/login, **data isolation between users**, bill upload, invoice GST split and PDF, and the
assistant's tool routing.

## Known limitations

- Tax rules are for FY 2025-26 and must be updated each Budget (`data/tax/rules_india.json`).
  Surcharge (income above ₹50 lakh), capital gains and foreign income are not modelled — the app says so.
- Photos need OCR (`requirements-ml.txt`); PDFs with text work out of the box.
- No password reset, email sending or payment reminders by email/WhatsApp yet.
- The overcharge check compares with standard HSN/SAC rates; some items have conditional rates, so it says
  "may have been overcharged" rather than asserting it.
- The web app is mobile-friendly; a Flutter mobile app can reuse the same API (`/api/v1/app/*`).
