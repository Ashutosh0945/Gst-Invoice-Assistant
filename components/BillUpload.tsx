"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Camera, Loader2, Upload } from "lucide-react";
import { app } from "@/lib/client";
import { ErrorNote } from "@/components/ui";

export function BillUpload({ compact = false }: { compact?: boolean }) {
  const router = useRouter();
  const file = useRef<HTMLInputElement>(null);
  const camera = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(picked: File | undefined) {
    if (!picked) return;
    const f = await shrinkPhoto(picked);
    if (!/\.(pdf|png|jpe?g|webp|tiff?)$/i.test(f.name)) { setError("Use a PDF or a photo (JPG, PNG, WEBP)."); return; }
    if (f.size > 4 * 1024 * 1024) { setError("That file is over 4 MB. Try a smaller PDF or a lower-resolution photo."); return; }
    setBusy(true);
    setError(null);
    try {
      const bill = await app.uploadBill(f);
      router.push(`/app/bills/${bill.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
      setBusy(false);
    }
  }

  return (
    <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files?.[0]); }}
      className={`rounded-2xl text-center transition ${compact ? "p-5" : "p-8"} ${drag ? "bg-base-deep shadow-neu-in ring-2 ring-accent/60" : "neu-inset"}`}>
      <input ref={file} type="file" accept=".pdf,image/*" className="sr-only" aria-label="Choose a bill" onChange={(e) => send(e.target.files?.[0])} />
      <input ref={camera} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take a photo of a bill" onChange={(e) => send(e.target.files?.[0])} />
      {busy ? (
        <div className="flex flex-col items-center gap-3 py-2">
          <Loader2 className="w-7 h-7 text-accent-soft animate-spin" aria-hidden />
          <p className="font-semibold">Reading and checking your bill…</p>
          <p className="text-xs text-ink-soft">GST rates, totals, QR code and duplicates</p>
        </div>
      ) : (
        <>
          {!compact && <p className="font-semibold">Add a bill</p>}
          {!compact && <p className="text-sm text-ink-soft mt-1 mb-5">Drop a PDF or photo here. We&apos;ll read it and check it.</p>}
          <div className="flex flex-wrap justify-center gap-3">
            <button className="btn-primary" onClick={() => camera.current?.click()}><Camera className="w-4 h-4" aria-hidden />Take photo</button>
            <button className="btn" onClick={() => file.current?.click()}><Upload className="w-4 h-4" aria-hidden />Upload file</button>
          </div>
        </>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
    </div>
  );
}

/** Phone photos are often 4–10 MB. Resize to at most 2000 px (plenty for reading a bill) and
 *  re-encode as JPEG so uploads are fast and stay under hosting request-size limits. */
async function shrinkPhoto(file: File): Promise<File> {
  if (!file.type.startsWith("image/") || file.size < 1.5 * 1024 * 1024) return file;
  try {
    const bmp = await createImageBitmap(file);
    const scale = Math.min(1, 2000 / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    canvas.getContext("2d")?.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    const blob: Blob | null = await new Promise((res) => canvas.toBlob(res, "image/jpeg", 0.85));
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;   // browser can't decode it (e.g. HEIC): upload the original
  }
}
