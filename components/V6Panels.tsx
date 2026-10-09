"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Brain, CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";

const inr = (v: number | string | null | undefined) => (v === null || v === undefined || v === "" ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Request failed");
  return d as T;
}
function useActor() {
  const [a, setA] = useState("");
  useEffect(() => { setA(localStorage.getItem("gstdesk-actor") || ""); }, []);
  return [a, (v: string) => { setA(v); try { localStorage.setItem("gstdesk-actor", v); } catch { /* */ } }] as const;
}
const ActorField = ({ actor, setActor }: { actor: string; setActor: (v: string) => void }) => (
  <label className="text-xs text-ink-soft">Your name (audit trail)<input className="field mt-1 py-2" value={actor} onChange={(e) => setActor(e.target.value)} /></label>);

// ----------------------------------------------------------------------------- GSTR-2B work queue
type QRow = { id: string; category: string; supplier: string | null; supplier_gstin: string | null; invoice_number: string; invoice_date: string | null;
  taxable_value: string; tax: string; notes: string | null; matched_invoice_id: string | null; resolution_status: string; assigned_to: string | null;
  candidates: Array<{ invoice_id: string; invoice_number: string; score: number }> | null };
export function Gstr2bQueue() {
  const [rows, setRows] = useState<QRow[] | null>(null);
  const [m, setM] = useState<Record<string, unknown> | null>(null);
  const [cat, setCat] = useState("");
  const [status, setStatus] = useState("open");
  const [actor, setActor] = useActor();
  const [err, setErr] = useState<string | null>(null);
  const load = () => {
    setRows(null);
    api<QRow[]>(`/api/v1/gstr2b/queue?${cat ? `category=${encodeURIComponent(cat)}&` : ""}${status ? `status=${status}` : ""}`).then(setRows).catch((e) => setErr(e.message));
    api<Record<string, unknown>>("/api/v1/gstr2b/metrics").then(setM).catch(() => undefined);
  };
  useEffect(load, [cat, status]); // eslint-disable-line react-hooks/exhaustive-deps
  const patch = async (id: string, body: Record<string, unknown>) => {
    if (!actor.trim()) { setErr("Enter your name first."); return; }
    try { await api(`/api/v1/gstr2b/records/${id}`, { method: "PATCH", body: JSON.stringify({ actor, ...body }) }); load(); } catch (e) { setErr((e as Error).message); }
  };
  const CATS = ["Matched", "Missing from GSTR-2B", "Missing from purchase records", "GSTIN mismatch", "Invoice-number mismatch", "Date mismatch",
    "Taxable-value mismatch", "Tax mismatch", "Potential duplicate", "Review required"];
  const defs = (m?.definitions || {}) as Record<string, string>;
  return (
    <div>
      {m && <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">{([["Imported records", m.total_imported_records, "total_imported_records"], ["Matched", m.matched_records, "matched_records"],
        ["Mismatches", m.mismatch_count, "mismatch_count"], ["Tax difference", inr(m.tax_difference as number), "tax_difference"],
        ["Taxable difference", inr(m.taxable_value_difference as number), ""], ["Missing from GSTR-2B", m.invoices_missing_from_gstr2b, ""],
        ["ITC potentially affected", inr(m.potential_itc_affected as number), "potential_itc_affected"], ["Resolved", m.resolved_issues, ""]] as Array<[string, unknown, string]>).map(([l, v, d]) =>
        <div key={l} className="neu-card p-4" title={defs[d] || ""}><div className="text-xs text-ink-soft">{l}</div><div className="text-xl font-extrabold tabular">{String(v)}</div></div>)}</div>}
      {m && <p className="text-xs text-ink-faint mb-4">{defs.unsupported}</p>}
      <div className="flex flex-wrap gap-3 items-end mb-4">
        <label className="text-xs text-ink-soft">Category<select className="field mt-1 py-2" value={cat} onChange={(e) => setCat(e.target.value)}><option value="">All</option>{CATS.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="text-xs text-ink-soft">Status<select className="field mt-1 py-2" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option value="open">Open</option><option value="under_review">Under review</option><option value="resolved">Resolved</option></select></label>
        <ActorField actor={actor} setActor={setActor} />
      </div>
      {err && <p role="alert" className="text-sm text-bad mb-3">{err}</p>}
      {!rows ? <div className="h-40 neu-card animate-pulse" /> : rows.length === 0 ? <div className="neu-card p-8 text-center text-ink-soft">Nothing in this view. Import a GSTR-2B file on the GSTR-2B page to start.</div> : (
        <div className="neu-card p-4 overflow-x-auto"><table className="tbl">
          <thead><tr><th>Category</th><th>Supplier</th><th>Invoice</th><th className="num">Taxable</th><th className="num">Tax</th><th>Why</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}>
            <td className="font-semibold text-sm">{r.category}</td><td className="text-sm">{r.supplier}<div className="text-xs text-ink-faint">{r.supplier_gstin}</div></td>
            <td>{r.matched_invoice_id ? <Link className="text-accent-soft" href={`/invoices/${r.matched_invoice_id}/investigate`}>{r.invoice_number}</Link> : r.invoice_number}<div className="text-xs text-ink-faint">{r.invoice_date}</div></td>
            <td className="num">{inr(r.taxable_value)}</td><td className="num">{inr(r.tax)}</td>
            <td className="text-xs text-ink-soft max-w-xs">{r.notes}{r.candidates?.length ? <div>Candidates: {r.candidates.map((c) => <Link key={c.invoice_id} className="text-accent-soft mr-2" href={`/invoices/${c.invoice_id}/investigate`}>{c.invoice_number}</Link>)}</div> : null}</td>
            <td className="text-xs">{r.resolution_status.replace("_", " ")}{r.assigned_to ? <div className="text-ink-faint">→ {r.assigned_to}</div> : null}</td>
            <td>{!r.id.startsWith("inv:") && <div className="flex flex-col gap-1">
              <button className="text-xs text-accent-soft text-left" onClick={() => patch(r.id, { assigned_to: actor, resolution_status: "under_review" })}>Assign to me</button>
              <button className="text-xs text-good text-left" onClick={() => { const note = prompt("Resolution note (what was done?)") || ""; if (note) patch(r.id, { resolution_status: "resolved", note }); }}>Resolve…</button>
              <Link className="text-xs text-accent-soft" href={`/gstr2b/explain/${r.id}`}>Explain</Link></div>}</td>
          </tr>)}</tbody></table></div>)}
    </div>
  );
}

// ----------------------------------------------------------------------------- duplicate review
type Side = { id: string; invoice_number: string | null; vendor: string | null; vendor_gstin: string | null; invoice_date: string | null; taxable: string; tax: string; total: string; status: string };
type Cand = { id: string; tier: string; score: number; score_label: string; signals: Record<string, unknown>; status: string; a: Side; b: Side };
export function DuplicateReview() {
  const [rows, setRows] = useState<Cand[] | null>(null);
  const [actor, setActor] = useActor();
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => api<Cand[]>("/api/v1/duplicates/candidates?status=open").then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);
  const decide = async (id: string, decision: string) => {
    if (!actor.trim()) { setMsg("Enter your name first."); return; }
    await api(`/api/v1/duplicates/candidates/${id}/decision`, { method: "POST", body: JSON.stringify({ actor, decision }) }); load();
  };
  const keys: Array<[keyof Side, string]> = [["vendor", "Vendor"], ["vendor_gstin", "GSTIN"], ["invoice_number", "Invoice no."], ["invoice_date", "Date"], ["taxable", "Taxable"], ["tax", "Tax"], ["total", "Total"]];
  return (
    <section className="neu-card p-5 mb-6">
      <div className="flex flex-wrap justify-between items-end gap-3"><div><h2 className="font-bold text-lg">Duplicate candidates to review</h2>
        <p className="text-sm text-ink-soft">Similar invoices from the same vendor. Nothing is deleted or merged — you decide. Recurring invoices (next number, same amount) are never flagged.</p></div>
        <div className="flex gap-2 items-end"><ActorField actor={actor} setActor={setActor} />
          <button className="btn py-2" onClick={async () => { const r = await api<{ new_candidates: number }>("/api/v1/duplicates/scan", { method: "POST" }); setMsg(`Scan found ${r.new_candidates} new candidate(s).`); load(); }}><RefreshCw className="w-4 h-4" aria-hidden />Scan all</button></div></div>
      {msg && <p className="text-sm text-ink-soft mt-2">{msg}</p>}
      {!rows ? <div className="h-24 neu-inset animate-pulse mt-4" /> : rows.length === 0 ? <p className="text-sm text-ink-soft mt-4">No open candidates.</p> :
        <ul className="space-y-4 mt-4">{rows.map((c) => (
          <li key={c.id} className="neu-inset p-4">
            <div className="flex flex-wrap justify-between gap-2 text-sm"><b className="capitalize">{c.tier} duplicate</b><span className="text-ink-faint">{c.score.toFixed(2)} — {c.score_label}</span></div>
            <div className="overflow-x-auto mt-2"><table className="tbl text-sm"><thead><tr><th>Field</th><th><Link className="text-accent-soft" href={`/invoices/${c.a.id}/investigate`}>Invoice A</Link></th><th><Link className="text-accent-soft" href={`/invoices/${c.b.id}/investigate`}>Invoice B</Link></th><th /></tr></thead>
              <tbody>{keys.map(([k, l]) => { const same = String(c.a[k] ?? "") === String(c.b[k] ?? ""); return (
                <tr key={k}><td className="text-ink-soft">{l}</td><td>{String(c.a[k] ?? "—")}</td><td>{String(c.b[k] ?? "—")}</td>
                  <td>{same ? <CheckCircle2 className="w-4 h-4 text-good" aria-label="same" /> : <XCircle className="w-4 h-4 text-warn" aria-label="differs" />}</td></tr>); })}</tbody></table></div>
            <div className="flex gap-2 mt-3"><button className="btn-primary py-1.5" onClick={() => decide(c.id, "confirmed")}>Confirm duplicate</button>
              <button className="btn py-1.5" onClick={() => decide(c.id, "dismissed")}>Not a duplicate</button></div>
          </li>))}</ul>}
    </section>
  );
}

// ----------------------------------------------------------------------------- ML anomaly panel (Risk Center)
type Score = { id: string; invoice_id: string; invoice_number: string | null; vendor: string | null; total: string | null; score: number; rank_pct: number; priority: string;
  data_sufficiency: string; model_version: string; review_status: string; signals: Array<{ feature: string; label: string; value: number; typical?: number }> };
export function AnomalyPanel() {
  const [model, setModel] = useState<Record<string, unknown> | null>(null);
  const [rows, setRows] = useState<Score[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [actor, setActor] = useActor();
  const load = () => { api<Record<string, unknown>>("/api/v1/ml/anomaly/model").then(setModel); api<Score[]>("/api/v1/ml/anomaly/scores?limit=50").then((r) => setRows(r.filter((x) => x.priority !== "low"))); };
  useEffect(load, []);
  const review = async (id: string, status: string) => {
    if (!actor.trim()) { setMsg("Enter your name first."); return; }
    const note = status === "reviewed" ? undefined : prompt("Note (optional)") || undefined;
    await api(`/api/v1/ml/anomaly/scores/${id}/review`, { method: "POST", body: JSON.stringify({ actor, status, note }) }); load();
  };
  return (
    <div className="neu-card p-5">
      <div className="flex flex-wrap justify-between gap-3 items-end">
        <div><h2 className="font-bold flex items-center gap-2"><Brain className="w-5 h-5 text-accent-soft" aria-hidden />ML anomaly signals</h2>
          <p className="text-sm text-ink-soft">Ensemble of Isolation Forest and robust statistics, chosen by benchmark. Each invoice is compared with the same vendor&apos;s earlier invoices. A signal is a reason to look — not proof of fraud.</p>
          {model && <p className="text-xs text-ink-faint mt-1">{model.status === "active" ? `Model ${String(model.version)} · trained on ${String(model.trained_on)} invoices` : String(model.message)}</p>}</div>
        <div className="flex gap-2 items-end"><ActorField actor={actor} setActor={setActor} />
          <button className="btn py-2" disabled={busy} onClick={async () => { setBusy(true); try { const r = await api<Record<string, unknown>>("/api/v1/ml/anomaly/train", { method: "POST" }); setMsg(r.status === "trained" ? `Trained model ${String(r.version)} on ${String(r.invoices)} invoices.` : String(r.message)); load(); } finally { setBusy(false); } }}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <RefreshCw className="w-4 h-4" aria-hidden />}Train / retrain</button></div>
      </div>
      {msg && <p className="text-sm mt-2">{msg}</p>}
      {!rows ? <div className="h-24 neu-inset animate-pulse mt-4" /> : rows.length === 0 ? <p className="text-sm text-ink-soft mt-4">No medium or high-priority signals.</p> : (
        <div className="overflow-x-auto mt-4"><table className="tbl"><thead><tr><th>Invoice</th><th>Vendor</th><th>Priority</th><th>Why</th><th>Data</th><th>Review</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td><Link className="font-semibold hover:text-accent-soft" href={`/invoices/${r.invoice_id}/investigate`}>{r.invoice_number || "—"}</Link><div className="text-xs text-ink-faint">{inr(r.total)}</div></td>
            <td className="text-sm">{r.vendor}</td><td className="text-sm capitalize">{r.priority}<div className="text-xs text-ink-faint">more unusual than {Math.round(r.rank_pct)}%</div></td>
            <td className="text-xs text-ink-soft max-w-sm">{r.signals.map((s) => `${s.label}: ${s.value}${s.typical !== undefined ? ` (typical ${s.typical})` : ""}`).join(" · ")}</td>
            <td className="text-xs">{r.data_sufficiency}</td>
            <td className="text-xs">{r.review_status === "open" ? <div className="flex flex-col gap-1">
              <button className="text-accent-soft text-left" onClick={() => review(r.id, "reviewed")}>Mark reviewed</button>
              <button className="text-ink-soft text-left" onClick={() => review(r.id, "dismissed")}>False positive</button>
              <button className="text-bad text-left" onClick={() => review(r.id, "confirmed")}>Confirm issue</button></div> : r.review_status}</td></tr>)}</tbody></table></div>)}
    </div>
  );
}

// ----------------------------------------------------------------------------- forecasts (Analytics)
type FC = { title: string; status: string; message?: string; model?: string; selection?: string; label: string;
  history: Array<{ month: string; value: number }>; forecast?: Array<{ month: string; forecast: number; low: number; high: number }>;
  evaluation?: Record<string, { MAE: number; RMSE: number; MASE: number | null; rolling_MAE: number }>; data_range?: { from: string; to: string; months: number };
  holdout?: { months: string[]; actual: number[] }; filled_missing_months: string[] };
export function ForecastPanel() {
  const [d, setD] = useState<Record<string, FC> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Record<string, FC>>("/api/v1/ml/forecast").then(setD).catch((e) => setErr(e.message)); }, []);
  if (err) return <p className="text-bad text-sm">{err}</p>;
  if (!d) return <div className="h-40 neu-card animate-pulse" />;
  return (
    <div className="space-y-4">{Object.entries(d).map(([k, f]) => {
      const money = k === "purchase_value" || k === "gst_on_purchases";
      const fmt = (v: number) => (money ? inr(v) : v.toFixed(1));
      return (
        <section key={k} className="neu-card p-5">
          <div className="flex flex-wrap justify-between gap-2"><h3 className="font-bold">{f.title}</h3>{f.model && <span className="text-xs text-ink-faint">Model: {f.model} · v forecast-v1</span>}</div>
          {f.status !== "ok" ? <p className="text-sm text-ink-soft mt-2">{f.message} {f.history.length ? `History: ${f.history.map((h) => `${h.month} ${fmt(h.value)}`).join(", ")}.` : ""}</p> : (<>
            <p className="text-xs text-warn mt-1">{f.label}</p>
            <div className="overflow-x-auto mt-3"><table className="tbl text-sm"><thead><tr><th>Month</th><th className="num">Value</th><th>Type</th></tr></thead><tbody>
              {f.history.slice(-6).map((h) => <tr key={h.month}><td>{h.month}</td><td className="num">{fmt(h.value)}</td><td className="text-xs text-ink-soft">actual{f.filled_missing_months.includes(h.month) ? " (no invoices — filled as 0)" : ""}</td></tr>)}
              {f.forecast!.map((x) => <tr key={x.month} className="bg-warn/5"><td>{x.month}</td><td className="num font-semibold">{fmt(x.forecast)}</td><td className="text-xs text-warn">forecast · range {fmt(x.low)}–{fmt(x.high)}</td></tr>)}
            </tbody></table></div>
            <details className="mt-3 text-sm"><summary className="cursor-pointer text-accent-soft">How it was evaluated</summary>
              <p className="text-xs text-ink-soft mt-2">{f.selection} Data {f.data_range?.from} to {f.data_range?.to} ({f.data_range?.months} months). Holdout months: {f.holdout?.months.join(", ")}.</p>
              <table className="tbl text-xs mt-2"><thead><tr><th>Model</th><th className="num">Rolling MAE</th><th className="num">Holdout MAE</th><th className="num">RMSE</th><th className="num">MASE</th></tr></thead>
                <tbody>{Object.entries(f.evaluation || {}).map(([m, e]) => <tr key={m} className={m === f.model ? "font-semibold" : ""}><td>{m}</td><td className="num">{fmt(e.rolling_MAE)}</td><td className="num">{fmt(e.MAE)}</td><td className="num">{fmt(e.RMSE)}</td><td className="num">{e.MASE ?? "—"}</td></tr>)}</tbody></table></details>
          </>)}
        </section>);
    })}</div>
  );
}

// ----------------------------------------------------------------------------- dashboard action centre extras
type AC = { definitions: Record<string, string>; overview: Record<string, number | null>; financial_impact: Record<string, number | string>;
  failed_jobs: Array<{ file: string; error: string; at: string | null }>; recent_activity: Array<{ action: string; actor: string; invoice_id: string | null; at: string | null }> };
export function ActionCenterExtras() {
  const [d, setD] = useState<AC | null>(null);
  useEffect(() => { api<AC>("/api/v1/ai/action-center").then(setD).catch(() => undefined); }, []);
  if (!d) return <div className="h-32 neu-card animate-pulse mt-6" />;
  const o = d.overview, f = d.financial_impact;
  return (
    <div className="grid gap-6 xl:grid-cols-3 mt-6">
      <section className="neu-card p-5">
        <h2 className="font-bold text-lg">Reconciliation &amp; review</h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between" title={d.definitions.gstr2b_match_rate}><dt>GSTR-2B match rate</dt><dd className="font-bold">{pct(o.gstr2b_match_rate)}</dd></div>
          <div className="flex justify-between"><dt><Link className="hover:text-accent-soft" href="/gstr2b/queue">Unresolved mismatches</Link></dt><dd className="font-bold">{o.unresolved_mismatches}</dd></div>
          <div className="flex justify-between"><dt><Link className="hover:text-accent-soft" href="/review">Invoices needing review</Link></dt><dd className="font-bold">{o.needs_review}</dd></div>
          <div className="flex justify-between"><dt>Open investigations</dt><dd className="font-bold">{o.open_investigations}</dd></div>
          <div className="flex justify-between"><dt><Link className="hover:text-accent-soft" href="/duplicates">Duplicate candidates</Link></dt><dd className="font-bold">{o.open_duplicate_candidates}</dd></div>
        </dl>
      </section>
      <section className="neu-card p-5">
        <h2 className="font-bold text-lg">Financial impact</h2>
        <dl className="mt-3 space-y-3 text-sm">
          <div><dt className="flex justify-between"><span>Confirmed differences</span><b>{inr(f.confirmed_differences as number)}</b></dt><dd className="text-xs text-ink-faint">{d.definitions.confirmed_differences}</dd></div>
          <div><dt className="flex justify-between"><span>Potentially affected ITC</span><b>{inr(f.potentially_affected_itc as number)}</b></dt><dd className="text-xs text-ink-faint">{d.definitions.potentially_affected_itc}</dd></div>
          <div><dt className="flex justify-between"><span>Requiring review</span><b>{inr(f.requiring_review as number)}</b></dt><dd className="text-xs text-ink-faint">{d.definitions.requiring_review}</dd></div>
          <div className="text-xs text-ink-faint"><Link className="text-accent-soft" href="/forecast">Estimated amounts</Link>: {String(f.estimated_note)}</div>
        </dl>
      </section>
      <section className="neu-card p-5">
        <h2 className="font-bold text-lg">Recent activity</h2>
        {d.recent_activity.length === 0 ? <p className="text-sm text-ink-soft mt-2">No activity yet.</p> :
          <ol className="mt-3 space-y-1.5 text-sm max-h-60 overflow-y-auto">{d.recent_activity.map((a, i) => <li key={i} className="flex justify-between gap-2">
            <span>{a.invoice_id ? <Link className="hover:text-accent-soft" href={`/invoices/${a.invoice_id}/investigate`}>{a.action.replaceAll("_", " ").toLowerCase()}</Link> : a.action.replaceAll("_", " ").toLowerCase()} <span className="text-ink-faint">· {a.actor}</span></span>
            <span className="text-xs text-ink-faint whitespace-nowrap">{a.at ? new Date(a.at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" }) : ""}</span></li>)}</ol>}
        {d.failed_jobs.length > 0 && <div className="mt-3"><b className="text-sm text-bad">Failed processing</b><ul className="text-xs text-ink-soft">{d.failed_jobs.map((j, i) => <li key={i}>{j.file}: {j.error}</li>)}</ul></div>}
      </section>
    </div>
  );
}
