// Copies the free, open-source Tesseract.js OCR engine into public/tesseract/ so it is served from
// this site (no external CDN, works offline once cached). Runs automatically after `npm install`.
import fs from "fs";
import path from "path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const nm = path.join(root, "node_modules");
const out = path.join(root, "public", "tesseract");
const files = [
  ["tesseract.js/dist/worker.min.js", "worker.min.js"],
  ["tesseract.js-core/tesseract-core-simd-lstm.wasm.js", "core/tesseract-core-simd-lstm.wasm.js"],
  ["tesseract.js-core/tesseract-core-lstm.wasm.js", "core/tesseract-core-lstm.wasm.js"],
  ["@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz", "lang/eng.traineddata.gz"],
];
let copied = 0;
for (const [src, dst] of files) {
  const from = path.join(nm, src), to = path.join(out, dst);
  if (!fs.existsSync(from)) { console.warn(`[ocr-assets] missing ${src} - browser OCR will be unavailable`); continue; }
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
  copied++;
}
console.log(`[ocr-assets] copied ${copied}/${files.length} Tesseract.js files to public/tesseract/`);
