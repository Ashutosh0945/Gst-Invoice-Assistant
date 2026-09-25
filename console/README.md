# Staff console (business dashboard)

A separate website for an accounts team: invoice register and review queue, GSTR-2B matching,
input tax credit control, e-invoice QR checks, vendor risk, analytics, PO matching, duplicates and
model accuracy. It shares the API and database with the personal app, but:

- only **staff** accounts can sign in (`scripts/create_staff.py`), checked by `middleware.ts` before any page renders;
- it only ever sees **business** invoices — personal-app bills are excluded by the API itself (`backend/api/deps.py`).

Local: `npm install` then `npm run dev -- -p 3001` (API running on :8000). See ../HOSTING.md, section 6.
