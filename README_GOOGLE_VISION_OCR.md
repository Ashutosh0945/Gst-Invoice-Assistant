# Google Cloud Vision OCR for GST Invoice Assistant

This patch adds Google Cloud Vision `DOCUMENT_TEXT_DETECTION` for JPG/PNG/WebP/TIFF invoice photos and scanned pages. It is designed for the existing Vercel Python API and does not require PaddleOCR, RapidOCR, ONNX Runtime, or a separate Railway service.

## 1. Google Cloud

1. Create/select a Google Cloud project.
2. Enable the **Cloud Vision API**.
3. Create an API key.
4. Restrict the key to the Cloud Vision API and keep it server-side.

Google documents `DOCUMENT_TEXT_DETECTION` for dense document text.

## 2. Vercel

Add this Environment Variable to the Vercel project:

`GOOGLE_VISION_API_KEY=<your restricted key>`

Optionally set:

`GOOGLE_VISION_TIMEOUT_S=30`

Then redeploy.

Do **not** use `NEXT_PUBLIC_GOOGLE_VISION_API_KEY`, commit the key to GitHub, or put the real key in `.env.example`.

## 3. Local development

Put the key in `.env` (which is already ignored by `.gitignore`):

```text
GOOGLE_VISION_API_KEY=your_key_here
GOOGLE_VISION_TIMEOUT_S=30
```

Start the existing FastAPI/Next.js app as usual.

## 4. What changes

`backend/ocr/engine.py` now prefers Google Cloud Vision when the key is configured. If it is not configured, the existing PaddleOCR/RapidOCR fallback remains available for local/self-hosted deployments.

The frontend upload screen does not need to change. Its existing OCR availability check will report `Google Cloud Vision` once the environment variable is present.

## 5. Test

After deployment, open:

`/api/v1/health`

and upload a clear JPG/PNG invoice from the existing Upload Invoice page. The photo should proceed through OCR, extraction, validation, and the existing Supabase persistence flow.
