"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Check, ClipboardCopy, Loader2, Mail, RefreshCw } from "lucide-react";
import { ai, type VendorMsg } from "@/lib/ai";

export default function VendorMessage() {
  const { id } = useParams<{ id: string }>();
  const draftKey = `gstdesk-msg-${id}`;
  const [m, setM] = useState<VendorMsg | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const gen = async () => {
    setBusy(true); setError(null);
    try { const r = await ai.vendorMessage(id); setM(r); setSubject(r.subject); setBody(r.body); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  };
  useEffect(() => {
    const saved = localStorage.getItem(draftKey);
    if (saved) { const d = JSON.parse(saved); setSubject(d.subject); setBody(d.body); setM({ ...d, source: "draft", note: null, reminder: "", facts: {} }); }
    else gen();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => { if (body) localStorage.setItem(draftKey, JSON.stringify({ subject, body })); }, [subject, body, draftKey]);

  return (
    <div className="max-w-3xl">
      <Link href={`/invoices/${id}`} className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink-strong mt-6"><ArrowLeft className="w-4 h-4" aria-hidden />Back to invoice</Link>
      <h1 className="text-[26px] font-extrabold tracking-tight pt-4">Ask the vendor for clarification</h1>
      <p className="text-ink-soft">Drafted from this invoice&apos;s actual details. <b>Review and edit before sending</b> — GST Desk never sends anything by itself.</p>
      {error && <p role="alert" className="text-bad text-sm mt-3">{error}</p>}
      <section className="neu-card p-5 mt-6 space-y-4">
        {!m && busy ? <div className="flex items-center gap-2 text-ink-soft"><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Drafting…</div> : <>
          <label className="block"><span className="text-sm text-ink-soft">Subject</span><input className="field mt-1" value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
          <label className="block"><span className="text-sm text-ink-soft">Message</span><textarea className="field mt-1 min-h-[300px] leading-relaxed" value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <p className="text-[11px] text-ink-faint">{m?.source === "ai" ? "Polished by AI; every number checked against the invoice." : m?.source === "draft" ? "Your saved draft (kept on this device)." : "Written from the invoice facts."} {m?.note || ""}</p>
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => { navigator.clipboard?.writeText(`${subject}\n\n${body}`); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              {copied ? <Check className="w-4 h-4" aria-hidden /> : <ClipboardCopy className="w-4 h-4" aria-hidden />}{copied ? "Copied" : "Copy"}</button>
            <a className="btn" href={`mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`}><Mail className="w-4 h-4" aria-hidden />Open in email app</a>
            <button className="btn" onClick={() => { localStorage.removeItem(draftKey); gen(); }} disabled={busy}><RefreshCw className="w-4 h-4" aria-hidden />Start over</button>
          </div></>}
      </section>
    </div>
  );
}
