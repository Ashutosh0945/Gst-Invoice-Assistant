// Free OCR in the user's browser (Tesseract.js 5, Apache-2.0). The engine and English model are
// self-hosted under /tesseract/ (see scripts/copy-ocr-assets.mjs), so nothing is sent to a third party
// and, once cached by the service worker, photos can be read offline too. Used only when the server
// has no OCR engine of its own (e.g. on Vercel).

type Worker = { recognize: (img: Blob) => Promise<{ data: { words: Array<{ text: string; confidence: number; bbox: { x0: number; y0: number; x1: number; y1: number } }> } }>;
  setParameters: (p: Record<string, string>) => Promise<unknown> };

let workerPromise: Promise<Worker> | null = null;
let onProgress: ((pct: number) => void) | null = null;

function getWorker(): Promise<Worker> {
  if (!workerPromise) {
    workerPromise = (async () => {
      const T = await import("tesseract.js");
      const w = (await T.createWorker("eng", 1, {
        workerPath: "/tesseract/worker.min.js", corePath: "/tesseract/core", langPath: "/tesseract/lang", gzip: true,
        logger: (m: { status: string; progress: number }) => {
          if (m.status === "recognizing text" && onProgress) onProgress(Math.round(m.progress * 100));
        },
      })) as unknown as Worker;
      await w.setParameters({ preserve_interword_spaces: "1" });
      return w;
    })().catch((e) => { workerPromise = null; throw e; });
  }
  return workerPromise;
}

/** OCR one image; returns the JSON the upload API accepts as `client_ocr`. */
export async function browserOcr(src: Blob | string, progress?: (pct: number) => void): Promise<string> {
  const blob = typeof src === "string" ? await (await fetch(src)).blob() : src;
  const bmp = await createImageBitmap(blob);
  const worker = await getWorker();
  onProgress = progress ?? null;
  try {
    const { data } = await worker.recognize(blob);
    const words = data.words.filter((w) => w.text.trim()).slice(0, 6000).map((w) => ({
      text: w.text.slice(0, 80), bbox: [w.bbox.x0, w.bbox.y0, w.bbox.x1, w.bbox.y1], conf: Math.max(0, Math.min(100, w.confidence)) }));
    return JSON.stringify({ engine: "tesseract.js 5.1.1", width: bmp.width, height: bmp.height, words });
  } finally {
    onProgress = null;
    bmp.close();
  }
}

/** For uploads that don't already have an analysed image (offline queue): ask the server for the
 *  OCR-ready image (the same one it will process), and OCR that. Returns null when the server can OCR. */
export async function ocrForUpload(file: Blob, name: string, optimize: boolean): Promise<string | null> {
  if (!file.type.startsWith("image/")) return null;
  let src: Blob | string = file;
  if (optimize) {
    const form = new FormData(); form.append("file", new File([file], name, { type: file.type }));
    const r = await fetch("/api/v1/capture/analyze", { method: "POST", body: form });
    if (r.ok) {
      const d = await r.json();
      if (d.browser_ocr_needed === false) return null;
      if (!d.capture_failed) src = d.ocr_ready || d.enhanced || file;
    }
  }
  return browserOcr(src);
}
