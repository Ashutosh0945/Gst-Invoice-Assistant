# v0.5.0 — AI camera capture optimization + Security & Compliance Center

## Camera capture flow (deterministic OpenCV, no AI)
Photo/file → `POST /api/v1/capture/analyze` (preview: document detection, crop, perspective, orientation/deskew,
enhancement, quality check; returns enhanced + OCR-ready images and warnings) → Retake / Use anyway →
`POST /api/v1/invoices?optimize=true` → the OCR-ready image (not the raw photo) goes into the EXISTING
OCR → extraction → validation → reconciliation pipeline; steps + quality are stored as a `CAPTURE_OPTIMIZED` audit entry.
The original image is never modified. Offline photos are queued with the optimize flag and processed the same way on sync.

Measured (real OCR, 8 synthetic phone photos, full extraction of invoice no./GSTIN/total/subtotal):
- raw photos 17/24 fields vs optimized 19/24 on readable photos; rotated and skewed photos improved (2→3), one angled desk photo dropped (4→3).
- Blurred and tiny photos read 0/4 either way; the quality check flags both as "poor" before upload (the main benefit).
- Black-and-white conversion was measured to hurt, so it's only used for extreme lighting; enhanced colour goes to OCR.
- Line items were not extracted from any photo (including a clean scan): a limitation of the existing rule extractor on OCR output.

## OCR engine
`backend/ocr/engine.py`: PaddleOCR (requirements-ml.txt) → RapidOCR (requirements-ocr.txt, same Paddle models) → unavailable.
Neither fits Vercel's Python size limit, so **photos can't be read on the current Vercel deployment**; System Health shows this.

## Security & Compliance Center (`/security`, `GET /api/v1/security/overview`, `GET /api/v1/security/events`)
Real checks only: API, database (+latency), DB TLS (pg_stat_ssl), schema, OpenRouter key validity (GET /key, value never returned),
PDF reading, OCR engine, RLS per table (pg_class.relrowsecurity) and whether the app role bypasses RLS, configuration
present/absent, CORS, API-key protection, user login (none), backups (not configured — app can't verify).
Audit trail (`access_events` table, new): API-key successes/denials and data access (invoice viewed/uploaded/modified/deleted,
GSTR-2B accessed/imported/deleted, reports generated, data downloaded, ITC recalculated). IPs masked; keys, tokens and bodies never stored;
auditing can never break a request. Alerts: ≥5 denials/15 min from one IP, ≥200 views/hour, ≥5 deletions/hour, services down, RLS off, API open.
Score = passed weight / weight of verifiable checks; unverifiable checks are listed and excluded. No certification is claimed.

## Database changes
New tables `access_events` (security audit) — created automatically at start. No existing table changed.

## Environment variables
None new required. To protect the API set `API_KEY` (note: the website's own browser requests don't send it, so setting it
today blocks the website too — proper user login is needed for real protection).

## Known limitations
- No user login exists, so login/logout/session events and per-user isolation can't be shown; auth events = API-key attempts.
- RLS is reported truthfully; on Supabase tables created by the app it will show Disabled, and the API role bypasses RLS anyway.
- Photo OCR unavailable on Vercel (size limit); works where requirements-ocr.txt or requirements-ml.txt can be installed.
- Push notifications to a closed app still not implemented (needs VAPID keys + push service).
- Real phone camera hardware and a live Supabase/Vercel run were not tested here.
