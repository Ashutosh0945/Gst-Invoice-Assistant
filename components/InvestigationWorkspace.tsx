"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FileText, History, Loader2, MessageSquarePlus, RefreshCw, Scale } from "lucide-react";

type Finding = { id: string; code: string; severity: string; message: string; field: string | null; line_no: number | null;
  expected: string | null; actual: string | null; difference: string | null; rule: string; recommended_action: string };
type WS = {
  invoice_id: string; status: string;
  investigation: { status: string; decision: string | null; decision_note: string | null; decided_by: string | null; decided_at: string | null };
  field_confidence: Record<string, number>; documents: Array<{ kind: string; filename: string | null; size_bytes: number; content_type: string }>;
  findings: Finding[]; gstr2b: { status: string | null; record: { match_status: string; notes: string | null; mismatch_fields: string[] | null } | null };
  duplicates: Array<{ id: string; other_invoice_id: string; tier: string; score: number; status: string }>;
  anomaly: { id: string; score: number; rank_pct: number; priority: string; data_sufficiency: string; model_version: string; review_status: string;
    signals: Array<{ feature: string; label: string; value: number; typical?: number; direction?: string }> } | null;
  notes: Array<{ author: string; text: string; at: string | null }>; audit: Array<{ action: string; actor: string; at: string | null }>;
};
const when = (s: string | null) => (s ? new Date(s).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");

async function post(url: string, body: unknown) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Request failed");
  return d;
}

export function InvestigationWorkspace({ id }: { id: string }) {
  const [ws, setWs] = useState<WS | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [doc, setDoc] = useState<"original" | "ocr_ready">("original");
  const load = () => fetch(`/api/v1/invoices/${id}/workspace`, { cache: "no-store" }).then((r) => r.json()).then(setWs).catch(() => setError("Couldn't load the workspace."));
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function act(kind: string, fn: () => Promise<unknown>, done: string) {
    if (!actor.trim()) { setMsg("Enter your name first — every action is recorded in the audit trail."); return; }
    setBusy(kind); setMsg(null);
    try { await fn(); await load(); setMsg(done); } catch (e) { setMsg(e instanceof Error ? e.message : "Failed"); } finally { setBusy(null); }
  }
  if (error) return <p className="text-bad text-sm">{error}</p>;
  if (!ws) return <div className="h-40 neu-card animate-pulse" />;
  const hasDoc = ws.documents.find((d) => d.kind === doc);
  const isImg = hasDoc && hasDoc.content_type.startsWith("image/");

  return (
    <section className="space-y-6 mb-8">
      <div className="neu-card p-5">
        <div className="flex flex-wrap items-end gap-3 justify-between">
          <div>
            <div className="label">INVESTIGATION</div>
            <div className="font-bold text-lg capitalize">{ws.investigation.status.replace("_", " ")}{ws.investigation.decision ? ` · decision: ${ws.investigation.decision}` : ""}</div>
            {ws.investigation.decided_by && <div className="text-xs text-ink-faint">by {ws.investigation.decided_by}, {when(ws.investigation.decided_at)}{ws.investigation.decision_note ? ` — “${ws.investigation.decision_note}”` : ""}</div>}
          </div>
          <label className="text-sm"><span className="text-ink-soft text-xs">Your name (recorded in the audit trail)</span>
            <input className="field mt-1" value={actor} onChange={(e) => setActor(e.target.value)} /></label>
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          <button className="btn py-1.5" disabled={!!busy} onClick={() => act("review", () => post(`/api/v1/invoices/${id}/investigation`, { actor, status: "under_review" }), "Marked as under review.")}>Mark under review</button>
          <button className="btn py-1.5" disabled={!!busy} onClick={() => act("reval", async () => {
            const r = await post(`/api/v1/invoices/${id}/revalidate`, { actor }); setMsg(`Re-ran validations: ${r.resolved.length} resolved, ${r.new.length} new.`); }, "Validations re-run.")}>
            {busy === "reval" ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <RefreshCw className="w-4 h-4" aria-hidden />}Re-run validations</button>
          {(["accepted", "corrected", "rejected", "escalated"] as const).map((d) => (
            <button key={d} className={d === "accepted" ? "btn-primary py-1.5" : "btn py-1.5"} disabled={!!busy}
              onClick={() => act(d, () => post(`/api/v1/invoices/${id}/investigation`, { actor, decision: d, note: note || undefined }), `Decision recorded: ${d}.`)}>
              <Scale className="w-4 h-4" aria-hidden />Decide: {d}</button>))}
        </div>
        <div className="flex gap-2 mt-3">
          <input className="field" placeholder="Investigation note (also used as the decision reason)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
          <button className="btn" disabled={!!busy || !note.trim()} onClick={() => act("note", () => post(`/api/v1/invoices/${id}/investigation`, { actor, note }), "Note added.").then(() => setNote(""))}>
            <MessageSquarePlus className="w-4 h-4" aria-hidden />Add note</button>
        </div>
        {msg && <p role="status" className="text-sm mt-2 text-ink-soft">{msg}</p>}
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="neu-card p-5">
          <div className="flex justify-between items-center mb-3"><h3 className="font-bold flex items-center gap-2"><FileText className="w-4 h-4" aria-hidden />Document</h3>
            {ws.documents.length > 1 && <div className="flex gap-1 p-1 rounded-xl bg-base-deep shadow-neu-in">
              {(["original", "ocr_ready"] as const).map((k) => <button key={k} onClick={() => setDoc(k)} className={`px-3 py-1 rounded-lg text-xs ${doc === k ? "bg-base shadow-neu-sm" : "text-ink-soft"}`}>{k === "original" ? "Original" : "OCR-ready"}</button>)}</div>}</div>
          {!hasDoc ? <p className="text-sm text-ink-soft">No stored file. Invoices uploaded before v0.6 didn't keep the original.</p>
            : isImg ? <img src={`/api/v1/invoices/${id}/document?kind=${doc}`} alt="Invoice document" className="w-full rounded-xl bg-white" /> // eslint-disable-line @next/next/no-img-element
            : <iframe src={`/api/v1/invoices/${id}/document?kind=${doc}`} title="Invoice document" className="w-full h-[520px] rounded-xl bg-white" />}
          {Object.keys(ws.field_confidence).length > 0 && <div className="mt-3 flex flex-wrap gap-2">{Object.entries(ws.field_confidence).map(([k, v]) =>
            <span key={k} className={`text-xs px-2 py-1 rounded-md ${v >= 0.9 ? "bg-good/10 text-good" : v >= 0.7 ? "bg-warn/10 text-warn" : "bg-bad/10 text-bad"}`}>{k.replaceAll("_", " ")} {Math.round(v * 100)}%</span>)}</div>}
        </div>
        <div className="neu-card p-5">
          <h3 className="font-bold mb-3">Findings &amp; evidence</h3>
          {ws.findings.length === 0 ? <p className="text-sm text-good">No findings.</p> : <ul className="space-y-3">{ws.findings.map((f) => (
            <li key={f.id} className="neu-inset p-3 text-sm">
              <div className="flex gap-2 items-start"><span className={`text-[11px] font-semibold px-1.5 py-0.5 rounded ${f.severity === "ERROR" ? "bg-bad/10 text-bad" : f.severity === "WARNING" ? "bg-warn/10 text-warn" : "bg-info/10 text-info"}`}>{f.severity}</span>
                <span className="font-semibold">{f.message}</span></div>
              <div className="text-xs text-ink-soft mt-1.5">Rule: {f.rule}{f.line_no ? ` · line ${f.line_no}` : ""}{f.field ? ` · field ${f.field}` : ""}</div>
              {(f.expected || f.actual) && <div className="text-xs mt-1">Expected <b>{f.expected ?? "—"}</b> · found <b>{f.actual ?? "—"}</b>{f.difference ? ` · difference ${f.difference}` : ""}</div>}
              <div className="text-xs mt-1"><span className="text-ink-faint">Next step: </span>{f.recommended_action}</div>
            </li>))}</ul>}
          {ws.gstr2b.record && <p className="text-sm mt-4"><b>GSTR-2B:</b> {ws.gstr2b.record.match_status.replaceAll("_", " ").toLowerCase()}{ws.gstr2b.record.notes ? ` — ${ws.gstr2b.record.notes}` : ""}</p>}
          {ws.duplicates.length > 0 && <div className="mt-4"><b className="text-sm">Possible duplicates</b>
            <ul className="text-sm mt-1">{ws.duplicates.map((d) => <li key={d.id}><Link className="text-accent-soft" href={`/invoices/${d.other_invoice_id}/investigate`}>Other invoice</Link> — {d.tier}, similarity {d.score.toFixed(2)} (not a probability), {d.status}</li>)}</ul></div>}
          {ws.anomaly && <div className="mt-4 text-sm"><b>ML anomaly signal:</b> {ws.anomaly.priority} priority (more unusual than {Math.round(ws.anomaly.rank_pct)}% of training invoices; data {ws.anomaly.data_sufficiency}; model {ws.anomaly.model_version})
            <ul className="list-disc pl-5 text-ink-soft">{ws.anomaly.signals.map((s, i) => <li key={i}>{s.label}: {s.value}{s.typical !== undefined ? ` (typical ${s.typical})` : ""}</li>)}</ul>
            <p className="text-[11px] text-ink-faint">A reason to look, not proof of fraud or non-compliance.</p></div>}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="neu-card p-5"><h3 className="font-bold mb-2">Notes</h3>
          {ws.notes.length === 0 ? <p className="text-sm text-ink-soft">No notes yet.</p> : <ul className="space-y-2 text-sm">{ws.notes.map((n, i) => <li key={i} className="neu-inset p-2.5"><b>{n.author}</b> <span className="text-xs text-ink-faint">{when(n.at)}</span><div>{n.text}</div></li>)}</ul>}</div>
        <div className="neu-card p-5"><h3 className="font-bold mb-2 flex items-center gap-2"><History className="w-4 h-4" aria-hidden />Audit history</h3>
          <ol className="text-sm space-y-1 max-h-72 overflow-y-auto">{ws.audit.map((a, i) => <li key={i} className="flex gap-2"><span className="text-ink-faint text-xs w-36 shrink-0">{when(a.at)}</span><span>{a.action.replaceAll("_", " ").toLowerCase()} <span className="text-ink-faint">by {a.actor}</span></span></li>)}</ol></div>
      </div>
    </section>
  );
}
