# Free OCR for photos (v0.6.1)

Vercel can't fit a server OCR engine, so photos used to fail with "This server has no OCR engine installed".
Now photos are read **in the user's browser** with **Tesseract.js 5.1.1** (free, open source, Apache-2.0).

## How it works
1. The photo is optimised on the server (crop, straighten, enhance) — `/api/v1/capture/analyze`.
2. The browser runs Tesseract.js on that optimised image (engine + English model are served from this
   site under `/tesseract/`; nothing goes to a third party; cached for offline use).
3. The recognised words are sent with the upload (`client_ocr` form field), validated, and used for
   extraction only if the server has no OCR engine of its own. The engine used is recorded in the audit log.

Engine order on the server: Google Vision (if `GOOGLE_VISION_API_KEY`) → local PaddleOCR/RapidOCR →
**OpenRouter vision model** (if `OPENROUTER_API_KEY`) → OCR.space (if `OCR_SPACE_API_KEY`) → browser Tesseract.js words → "no OCR".

## Vision-language-model OCR (OpenRouter)
`backend/ocr/vlm.py` sends the page image to `nvidia/nemotron-3.5-super-vl:free` and turns its text segments
(+ approximate 0-1000 boxes) into the same word list the other engines produce. Uses the existing
`OPENROUTER_API_KEY`; nothing to install. Settings: `VLM_OCR_ENABLED` (default true), `OPENROUTER_OCR_MODEL`.
- Model boxes are approximate and treated as untrusted; unusable ones fall back to a reading-order layout.
- The free tier is rate limited. On any failure the chain continues to OCR.space / browser OCR, and while the VLM is
  the only server engine the browser still runs Tesseract.js as a safety net (`browser_ocr_needed`).
- The engine used is recorded in the audit log (`OCR_ENGINE`). Invoice images are sent to OpenRouter/NVIDIA's provider.
- Not yet benchmarked on real invoices; compare against Tesseract.js before relying on it for auto-approval.

## Measured (12 unseen synthetic invoices, real Tesseract.js, through the real upload API)
| Input | Before (no OCR) | Browser OCR |
|---|---|---|
| Clean scans — key fields correct | 0% | 98.3% (11/12 fully correct) |
| Phone-style photos + capture optimisation | 0% | 95.0% (9/12 fully correct) |
Fields: GSTIN, invoice number, date, subtotal, grand total. About 1 s per page in Node, ~8 s per photo in the
browser test (including model download on first use). Synthetic invoices — real photos will vary.

## Safe GSTIN repair
OCR look-alikes (O/0, I/1, S/5…) in GSTINs are fixed by position and checksum **only when exactly one fix
is valid**; ambiguous ones are left unchanged so validation flags them for a person.

## Setup
Nothing extra: `npm install` copies the OCR files into `public/tesseract/` (scripts/copy-ocr-assets.mjs;
also runs before `npm run build`, so Vercel does it automatically).
Optional server OCR for scanned multi-page PDFs: get a free key at https://ocr.space/ocrapi and set
`OCR_SPACE_API_KEY` in Vercel. (Free tier limits apply; files are sent to OCR.space.)

## Limits
- Browser OCR reads image uploads; scanned PDFs without a text layer need a server engine (e.g. OCR.space).
- First use downloads ~11 MB of OCR files (then cached). Very old browsers without WebAssembly can't run it.
