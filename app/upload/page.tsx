"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Camera, CheckCircle2, CircleAlert, FileUp, Loader2, Save, Search, WifiOff } from "lucide-react";
import { type InvoiceDetail } from "@/lib/api";
import { enqueue, hashFile, markUploaded, wasUploaded } from "@/lib/offline-queue";
import { ErrorNote } from "@/components/ui";

type Stage = "idle" | "uploading" | "processing" | "complete" | "queued" | "error";
const PIPE_PDF = ["Uploading", "OCR / reading", "Extraction", "Validation & reconciliation", "Complete"];
const PIPE_IMG = ["Detecting document", "Enhancing", "Quality check", "Uploading", "OCR", "Extraction", "Complete"];
type Capture = { steps: Array<{ step: string; done: boolean; detail: string }>; enhanced: string; ocr_ready: string | null;
  ocr_ready_same_as_enhanced: boolean; ocr_available: boolean; ocr_engine: string | null;
  quality: { verdict: "good" | "fair" | "poor"; score: number; warnings: Array<{ code: string; severity: string; message: string }>; metrics: Record<string, unknown> } };
const FIELDS: Array<[keyof InvoiceDetail & string, string, string]> = [
  ["vendor_name_raw", "Vendor", "vendor_name"], ["vendor_gstin_raw", "Vendor GSTIN", "vendor_gstin"],
  ["invoice_number", "Invoice number", "invoice_number"], ["invoice_date", "Invoice date", "invoice_date"],
  ["grand_total", "Grand total", "grand_total"],
];

function upload(file: File, onProgress: (p: number) => void, optimize = false): Promise<InvoiceDetail> {
  // XMLHttpRequest (not fetch) so we can show real upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/invoices${optimize ? "?optimize=true" : ""}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((100 * e.loaded) / e.total));
    xhr.onload = () => {
      let data: { detail?: string } | InvoiceDetail = {} as InvoiceDetail;
      try { data = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as InvoiceDetail);
      else reject(Object.assign(new Error((data as { detail?: string }).detail || `The server returned an error (${xhr.status}).`), { network: false }));
    };
    xhr.onerror = () => reject(Object.assign(new Error("Network error"), { network: true }));
    const form = new FormData(); form.append("file", file); xhr.send(form);
  });
}

export default function UploadPage() {
  const fileInput = useRef<HTMLInputElement>(null);
  const camInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [dupWarn, setDupWarn] = useState(false);
  const [result, setResult] = useState<InvoiceDetail | null>(null);
  const [cap, setCap] = useState<Capture | null>(null);
  const [capBusy, setCapBusy] = useState(false);
  const [view, setView] = useState<"original" | "enhanced" | "ocr">("enhanced");
  const isImage = !!file && file.type.startsWith("image/");

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  function pick(f: File | undefined | null) {
    if (!f) return;
    if (!/\.(pdf|png|jpe?g|tiff?|webp)$/i.test(f.name)) { setError("Use a PDF, PNG, JPG, TIFF or WEBP file."); return; }
    if (f.size > 4 * 1024 * 1024) { setError("That file is over 4 MB. Use a smaller file or a lower-resolution photo."); return; }
    setError(null); setDupWarn(false); setResult(null); setStage("idle"); setFile(f); setCap(null);
    setPreview(URL.createObjectURL(f));
    if (f.type.startsWith("image/") && navigator.onLine) analyse(f);
  }

  async function analyse(f: File) {
    // Real processing on the server: document detection, crop, perspective, enhancement, quality check.
    setCapBusy(true);
    try {
      const form = new FormData(); form.append("file", f);
      const res = await fetch("/api/v1/capture/analyze", { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Couldn't analyse the photo.");
      setCap(data as Capture); setView("enhanced");
    } catch (e) { setError(e instanceof Error ? `${e.message} You can still upload the original.` : "Analysis failed."); }
    finally { setCapBusy(false); }
  }

  async function run(confirmDuplicate = false) {
    if (!file) { setError("Choose an invoice file first."); return; }
    setError(null);
    const hash = await hashFile(file);
    if (!confirmDuplicate && (await wasUploaded(hash))) { setDupWarn(true); return; }
    setDupWarn(false);
    if (!navigator.onLine) {
      const added = await enqueue(file, hash, isImage);
      setStage("queued");
      if (!added) setError("This file is already waiting in the offline queue.");
      return;
    }
    setStage("uploading"); setProgress(0);
    try {
      const inv = await upload(file, (p) => { setProgress(p); if (p >= 100) setStage("processing"); }, isImage);
      await markUploaded(hash, inv.id);
      setResult(inv); setStage("complete");
    } catch (e) {
      if ((e as { network?: boolean }).network) {      // connection dropped: keep it safe and retry later
        await enqueue(file, hash, isImage); setStage("queued");
      } else { setError(e instanceof Error ? e.message : "Upload failed."); setStage("error"); }
    }
  }

  const PIPE = isImage ? PIPE_IMG : PIPE_PDF;
  const off = isImage ? 3 : 0;   // photo stages 0-2 happen during analysis, before upload
  const activeIdx = capBusy ? 0 : stage === "uploading" ? off : stage === "processing" ? off + 1 : stage === "complete" ? PIPE.length - 1
    : -1;   // nothing is shown as "in progress" until it really is

  return (
    <div>
      <header className="pt-8 pb-6">
        <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">Upload invoice</h1>
        <p className="text-ink-soft mt-1">The invoice is read, checked against GST rules, matched to its PO, QR-verified and scored in one pass.</p>
      </header>

      <div className="grid gap-6 xl:grid-cols-2">
        <section className="neu-card p-5">
          <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files?.[0]); }}
            className={`rounded-2xl p-8 text-center transition ${drag ? "ring-2 ring-accent/60 bg-base-deep" : "neu-inset"}`}>
            <div className="icon-tile mx-auto w-16 h-16"><FileUp className="w-7 h-7 text-accent-soft" aria-hidden /></div>
            <p className="mt-4 font-semibold">{file ? file.name : "Drop an invoice here"}</p>
            <p className="text-sm text-ink-soft">{file ? `${Math.round(file.size / 1024)} KB` : "PDF or photo · works offline too"}</p>
            <input ref={fileInput} type="file" accept=".pdf,image/*" className="sr-only" aria-label="Choose invoice file" onChange={(e) => pick(e.target.files?.[0])} />
            <input ref={camInput} type="file" accept="image/*" capture="environment" className="sr-only" aria-label="Take a photo of the invoice" onChange={(e) => pick(e.target.files?.[0])} />
            <div className="flex flex-wrap justify-center gap-3 mt-5">
              <button className="btn" onClick={() => fileInput.current?.click()} disabled={stage === "uploading" || stage === "processing"}>Choose file</button>
              <button className="btn" onClick={() => camInput.current?.click()} disabled={stage === "uploading" || stage === "processing"}><Camera className="w-4 h-4" aria-hidden />Take photo</button>
              <button className="btn-primary" onClick={() => run()} disabled={!file || capBusy || stage === "uploading" || stage === "processing" || cap?.quality.verdict === "poor"}>
                {stage === "uploading" || stage === "processing" ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Processing…</> : "Process invoice"}</button>
            </div>
            {capBusy && <p className="mt-4 text-sm text-ink-soft flex items-center justify-center gap-2"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Detecting the invoice and checking photo quality…</p>}
            {cap && cap.quality.verdict !== "good" && (
              <div role="alert" className={`mt-4 text-left text-sm rounded-xl p-3 ${cap.quality.verdict === "poor" ? "bg-bad/10" : "bg-warn/10"}`}>
                <b className={cap.quality.verdict === "poor" ? "text-bad" : "text-warn"}>{cap.quality.verdict === "poor" ? "This photo will probably read badly." : "Photo quality could be better."}</b>
                <ul className="list-disc pl-5 mt-1 text-ink-soft">{cap.quality.warnings.map((w) => <li key={w.code}>{w.message}</li>)}</ul>
                <div className="flex gap-2 mt-2">
                  <button className="btn py-1.5" onClick={() => camInput.current?.click()}><Camera className="w-4 h-4" aria-hidden />Retake</button>
                  {cap.quality.verdict === "poor" && <button className="btn py-1.5" onClick={() => { setCap({ ...cap, quality: { ...cap.quality, verdict: "fair" } }); }}>Use anyway</button>}
                </div>
              </div>)}
            {cap && !cap.ocr_available && (
              <p role="alert" className="mt-3 text-sm rounded-xl bg-warn/10 text-warn p-3">This server has no OCR engine installed, so photos can&apos;t be read here yet. Upload a PDF, or see Security &amp; Compliance → System health.</p>)}
            {dupWarn && (
              <div role="alert" className="mt-4 text-sm rounded-xl bg-warn/10 text-warn p-3">This exact file was already uploaded from this device.
                <button className="underline ml-2" onClick={() => run(true)}>Upload again anyway</button></div>)}
            {error && <ErrorNote>{error}</ErrorNote>}
            {stage === "queued" && (
              <div role="status" className="mt-4 text-sm rounded-xl bg-info/10 text-info p-3 flex items-center gap-2 justify-center">
                <WifiOff className="w-4 h-4" aria-hidden />Saved on this device. It will upload automatically when you&apos;re online
                (<Link href="/settings#offline" className="underline">view queue</Link>).</div>)}
          </div>

          <ol className="flex flex-wrap gap-2 mt-5" aria-label="Processing progress">
            {PIPE.map((p, i) => {
              const done = activeIdx > i || stage === "complete" || (isImage && !!cap && i < 3);
              const active = (capBusy && i < 3) || activeIdx === i || (stage === "processing" && i > off && i < PIPE.length - 1);
              return (
                <li key={p} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs ${done ? "bg-good/10 text-good" : active ? "bg-accent/15 text-accent-soft" : "bg-base shadow-neu-sm text-ink-faint"}`}>
                  {done ? <CheckCircle2 className="w-3.5 h-3.5" aria-hidden /> : active ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden /> : null}
                  {p}{i === off && stage === "uploading" ? ` ${progress}%` : ""}
                </li>);
            })}
          </ol>
          {stage === "processing" && <p className="text-xs text-ink-faint mt-2">OCR, extraction, validation and reconciliation run together on the server; the result appears when they finish.</p>}
        </section>

        <section className="neu-card p-5 min-h-[320px]">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <h2 className="font-bold">Document preview</h2>
            {cap && <div className="flex gap-1 p-1 rounded-xl bg-base-deep shadow-neu-in" role="tablist">
              {([["original", "Original"], ["enhanced", "Enhanced"], ["ocr", "OCR-ready"]] as const).map(([k, l]) => (
                <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)} className={`px-3 py-1 rounded-lg text-xs ${view === k ? "bg-base shadow-neu-sm text-ink-strong" : "text-ink-soft"}`}>{l}</button>))}</div>}
          </div>
          {cap && view !== "original" ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={view === "ocr" ? (cap.ocr_ready || cap.enhanced) : cap.enhanced} alt={view === "ocr" ? "OCR-ready image" : "Enhanced image"} className="w-full max-h-[460px] object-contain rounded-xl bg-white" />
              {view === "ocr" && cap.ocr_ready_same_as_enhanced && <p className="text-xs text-ink-faint mt-1">The enhanced image is what OCR reads (it measured best on test photos).</p>}
              <ul className="mt-3 space-y-1 text-xs">{cap.steps.map((st) => <li key={st.step} className="flex gap-2"><CheckCircle2 className={`w-3.5 h-3.5 shrink-0 ${st.done ? "text-good" : "text-ink-faint"}`} aria-hidden /><span><b>{st.step}:</b> <span className="text-ink-soft">{st.detail}</span></span></li>)}</ul>
              <p className="text-[11px] text-ink-faint mt-2">Your original photo is kept unchanged; only the OCR-ready copy is read.</p>
            </>
          ) : !preview ? <p className="text-sm text-ink-soft">Your file will appear here.</p>
            : file?.type === "application/pdf" ? <iframe src={preview} title="Invoice preview" className="w-full h-[460px] rounded-xl bg-white" />
            // eslint-disable-next-line @next/next/no-img-element
            : <img src={preview} alt="Invoice preview" className="w-full max-h-[460px] object-contain rounded-xl bg-white" />}
        </section>
      </div>

      {result && <Result inv={result} onSaved={setResult} />}
    </div>
  );
}

function Result({ inv, onSaved }: { inv: InvoiceDetail; onSaved: (i: InvoiceDetail) => void }) {
  const conf = inv.extraction_confidence || {};
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(FIELDS.map(([k]) => [k, String(inv[k] ?? "")])));
  const [reviewer, setReviewer] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const changed = FIELDS.filter(([k]) => vals[k] !== String(inv[k] ?? ""));

  async function save() {
    if (!reviewer.trim()) { setMsg("Enter your name to save corrections."); return; }
    setSaving(true); setMsg(null);
    try {
      const header = Object.fromEntries(changed.map(([k]) => [k, vals[k] === "" ? null : vals[k]]));
      const res = await fetch(`/api/v1/invoices/${inv.id}/correct`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, header_fields: header, notes: "Corrected on upload screen" }) });
      if (!res.ok) throw new Error("Couldn't save the corrections.");
      onSaved(await res.json()); setMsg("Saved. Your corrections also help measure and improve reading accuracy.");
    } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); } finally { setSaving(false); }
  }

  const errors = inv.findings.filter((f) => f.severity !== "INFO");
  return (
    <section className="neu-card p-5 mt-6 rise">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-bold text-lg">{inv.invoice_number || inv.source_filename}</h2>
        <div className="flex gap-2">
          <Link href={`/invoices/${inv.id}/investigate`} className="btn py-1.5"><Search className="w-4 h-4" aria-hidden />Investigate</Link>
          <Link href={`/invoices/${inv.id}`} className="btn-primary py-1.5">Open invoice</Link>
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2 mt-4">
        <div>
          <div className="label mb-2">EXTRACTED DATA · CORRECT ANYTHING THAT&apos;S WRONG</div>
          <div className="space-y-2.5">
            {FIELDS.map(([k, label, ck]) => {
              const c = typeof conf[ck] === "number" ? (conf[ck] as number) : null;
              const tone = c === null ? "text-ink-faint" : c >= 0.9 ? "text-good" : c >= 0.7 ? "text-warn" : "text-bad";
              const missing = !inv[k];
              return (
                <label key={k} className="block">
                  <span className="flex justify-between text-xs"><span className="text-ink-soft">{label}</span>
                    <span className={tone}>{c === null ? (missing ? "not found" : "") : `${Math.round(c * 100)}% sure`}</span></span>
                  <input className={`field mt-1 ${missing ? "ring-2 ring-bad/50" : c !== null && c < 0.7 ? "ring-2 ring-warn/50" : ""}`}
                    value={vals[k]} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} type={k === "invoice_date" ? "date" : "text"} />
                </label>);
            })}
          </div>
          {changed.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-2 items-end">
              <label className="flex-1 min-w-[160px]"><span className="text-xs text-ink-soft">Your name</span>
                <input className="field mt-1" value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></label>
              <button className="btn-primary" onClick={save} disabled={saving}><Save className="w-4 h-4" aria-hidden />{saving ? "Saving…" : `Save ${changed.length} correction${changed.length > 1 ? "s" : ""}`}</button>
            </div>)}
          {msg && <p className="text-sm mt-2 text-ink-soft">{msg}</p>}
        </div>
        <div>
          <div className="label mb-2">CHECK RESULTS</div>
          {errors.length === 0 ? <p className="flex items-center gap-2 text-good text-sm"><CheckCircle2 className="w-4 h-4" aria-hidden />Passed every automated check.</p> : (
            <ul className="space-y-2">{errors.map((f) => (
              <li key={f.id} className="flex gap-2 text-sm neu-inset px-3 py-2.5"><CircleAlert className={`w-4 h-4 shrink-0 mt-0.5 ${f.severity === "ERROR" ? "text-bad" : "text-warn"}`} aria-hidden />{f.message}</li>))}</ul>)}
          <p className="text-xs text-ink-faint mt-3">Status: {inv.status.replaceAll("_", " ").toLowerCase()} · Confidence {Math.round(Number(inv.confidence_score || 0) * 100)}%</p>
        </div>
      </div>
    </section>
  );
}
