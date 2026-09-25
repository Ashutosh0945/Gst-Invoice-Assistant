"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import { api, formatMoney, formatPercent, type InvoiceDetail } from "@/lib/api";
import { Card, ErrorNote, PageHeader } from "@/components/ui";
import { EinvBadge, ItcBadge, SeverityDot, StatusBadge } from "@/components/badges";

const STEPS = ["Reading the document", "Checking GST rules", "Matching purchase orders", "Verifying e-invoice QR", "Assessing tax credit"];

export default function UploadPage() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InvoiceDetail | null>(null);

  async function pick(picked: File | undefined | null) {
    if (!picked) return;
    const f = await shrinkPhoto(picked);
    if (!/\.(pdf|png|jpe?g|tiff?|webp)$/i.test(f.name)) {
      setError("That file type isn't supported. Use a PDF, PNG, JPG, TIFF or WEBP.");
      return;
    }
    if (f.size > 4 * 1024 * 1024) {
      setError("That file is over 4 MB. Use a smaller PDF or a lower-resolution photo.");
      return;
    }
    setError(null);
    setFile(f);
  }

  async function run() {
    if (!file) {
      setError("Choose an invoice file first.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.uploadInvoice(file));
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <PageHeader title="Upload invoice" subtitle="The invoice is read, checked against GST rules, matched to its PO, QR-verified and scored in one pass." />
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <Card>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
            className={`rounded-2xl p-10 text-center transition ${drag ? "shadow-neu-in bg-base-deep" : "neu-inset"}`}
          >
            <div className="icon-tile mx-auto w-16 h-16"><FileUp className="w-7 h-7 text-accent-soft" aria-hidden /></div>
            <p className="mt-5 font-semibold">{file ? file.name : "Drop an invoice here"}</p>
            <p className="text-sm text-ink-soft mt-1">{file ? `${(file.size / 1024).toFixed(0)} KB` : "PDF or image, one invoice per file"}</p>
            <input ref={input} type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif,.webp" className="sr-only"
              onChange={(e) => pick(e.target.files?.[0])} aria-label="Choose invoice file" />
            <div className="flex justify-center gap-3 mt-6">
              <button className="btn" onClick={() => input.current?.click()} disabled={busy}>Choose file</button>
              <button className="btn-primary" onClick={run} disabled={busy || !file}>
                {busy ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden /> Processing…</> : "Process invoice"}
              </button>
            </div>
            {error && <ErrorNote>{error}</ErrorNote>}
          </div>
        </Card>
        <Card title="What happens">
          <ol className="space-y-3">
            {STEPS.map((s, i) => (
              <li key={s} className="flex items-center gap-3 text-sm">
                <span className={`w-7 h-7 rounded-lg grid place-items-center text-xs font-bold ${busy ? "bg-accent/20 text-accent-soft" : "bg-base shadow-neu-sm text-ink-soft"}`}>{i + 1}</span>
                {s}
              </li>
            ))}
          </ol>
        </Card>
      </div>

      {result && (
        <Card className="mt-6 rise" title={result.invoice_number || result.source_filename} action={<StatusBadge value={result.status} />}>
          <div className="grid gap-3 sm:grid-cols-4">
            {[["Grand total", formatMoney(result.grand_total)], ["Confidence", formatPercent(result.confidence_score, 1)],
              ["Findings", String(result.findings.length)], ["Claimable ITC", formatMoney(result.itc?.eligible_itc)]].map(([l, v]) => (
              <div key={l} className="neu-inset p-3.5"><div className="text-xs text-ink-soft">{l}</div><div className="font-bold tabular mt-0.5">{v}</div></div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2 mt-4"><ItcBadge value={result.itc?.status} /><EinvBadge value={result.einvoice_status} /></div>
          {result.findings.filter((f) => f.severity !== "INFO").length > 0 && (
            <ul className="mt-4 space-y-2">
              {result.findings.filter((f) => f.severity !== "INFO").map((f) => (
                <li key={f.id} className="flex items-start gap-2.5 text-sm"><span className="mt-1.5"><SeverityDot severity={f.severity} /></span>{f.message}</li>
              ))}
            </ul>
          )}
          <Link href={`/invoices/${result.id}`} className="btn-primary mt-5">
            Open invoice{result.status === "NEEDS_REVIEW" ? " and review" : ""}
          </Link>
        </Card>
      )}
    </div>
  );
}

/** Resize large phone photos (max 2000 px, JPEG) so uploads are quick and within hosting limits. */
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
    return blob ? new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch {
    return file;
  }
}
