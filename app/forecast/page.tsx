"use client";

import { useEffect, useState } from "react";
import { FlaskConical, Loader2, TrendingUp } from "lucide-react";
import { ai, inr, type Forecast, type WhatIf } from "@/lib/ai";
import { StackedBars } from "@/components/charts";
import { ForecastPanel } from "@/components/V6Panels";

export default function ForecastPage() {
  const [fc, setFc] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scenario, setScenario] = useState("purchases_change");
  const [pct, setPct] = useState(20);
  const [invoiceId, setInvoiceId] = useState("");
  const [invoices, setInvoices] = useState<Array<{ id: string; invoice_number: string | null; vendor_name_raw: string | null }>>([]);
  const [w, setW] = useState<WhatIf | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    ai.forecast(3).then(setFc).catch((e) => setError(e.message));
    fetch("/api/v1/invoices?limit=200").then((r) => r.json()).then(setInvoices).catch(() => undefined);
  }, []);
  const run = async () => {
    setBusy(true); setError(null);
    try { setW(await ai.whatif(scenario === "purchases_change" ? { scenario, pct } : { scenario, invoice_id: invoiceId })); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  };

  const bars = fc ? [...fc.history.slice(-9).map((h) => ({ label: h.month.slice(2), actual: h.gst, estimate: 0 })),
    ...fc.forecast.map((f) => ({ label: `${f.month.slice(2)}*`, actual: 0, estimate: f.estimate }))] : [];

  return (
    <div className="max-w-5xl">
      <header className="pt-8 pb-6">
        <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">Forecast &amp; what-if</h1>
        <p className="text-ink-soft mt-1">Estimates and simulations only. They never change your records or statutory GST calculations.</p>
      </header>

      <h2 className="font-bold text-lg mb-3">Forecasts with model evaluation</h2>
      <ForecastPanel />
      <section className="neu-card p-5 mt-6">
        <h2 className="font-bold text-lg flex items-center gap-2"><TrendingUp className="w-5 h-5 text-accent-soft" aria-hidden />GST forecast</h2>
        {!fc && !error && <div className="h-48 animate-pulse neu-inset mt-4" />}
        {fc && <>
          <p className="text-sm text-ink-soft mt-1">{fc.what}. <b className="text-warn">{fc.label}</b> GST Desk records purchase invoices only, so this is GST you pay on purchases (and can usually claim as ITC), not your output liability.</p>
          {fc.status === "insufficient_history" ? <p className="mt-4 neu-inset p-4 text-sm">{fc.message}</p> : <>
            <div className="mt-4"><StackedBars data={bars} format={(n) => inr(n)} series={[
              { key: "actual", label: "Actual", color: "rgb(var(--c-accent))" }, { key: "estimate", label: "Estimate", color: "rgb(var(--c-warn))" }]} /></div>
            <p className="text-xs text-ink-faint">* estimated months · {fc.method} · {fc.message}</p>
            <div className="overflow-x-auto -mx-3 mt-3"><table className="tbl">
              <thead><tr><th>Month</th><th className="num">Estimate</th><th className="num">Likely range (~80%)</th></tr></thead>
              <tbody>{fc.forecast.map((f) => <tr key={f.month}><td>{f.month}</td><td className="num font-semibold">{inr(f.estimate)}</td><td className="num text-ink-soft">{inr(f.low)} – {inr(f.high)}</td></tr>)}</tbody>
            </table></div>
          </>}
        </>}
      </section>

      <section className="neu-card p-5 mt-6">
        <h2 className="font-bold text-lg flex items-center gap-2"><FlaskConical className="w-5 h-5 text-accent-soft" aria-hidden />What-if simulator</h2>
        <div className="flex flex-wrap gap-3 items-end mt-4">
          <label><span className="text-xs text-ink-soft">Scenario</span>
            <select className="field mt-1" value={scenario} onChange={(e) => { setScenario(e.target.value); setW(null); }}>
              <option value="purchases_change">Purchases increase or decrease</option>
              <option value="not_in_2b">An invoice is not in GSTR-2B</option>
              <option value="unpaid_180">A vendor isn&apos;t paid within 180 days</option>
            </select></label>
          {scenario === "purchases_change" ? (
            <label><span className="text-xs text-ink-soft">Change: {pct > 0 ? "+" : ""}{pct}%</span>
              <input type="range" min={-50} max={100} step={5} value={pct} onChange={(e) => setPct(Number(e.target.value))} className="block w-56 mt-3 accent-[rgb(var(--c-accent))]" aria-label="Percentage change" /></label>
          ) : (
            <label className="min-w-[240px]"><span className="text-xs text-ink-soft">Invoice</span>
              <select className="field mt-1" value={invoiceId} onChange={(e) => setInvoiceId(e.target.value)}>
                <option value="">Choose an invoice…</option>
                {invoices.map((i) => <option key={i.id} value={i.id}>{i.invoice_number || "—"} · {i.vendor_name_raw || ""}</option>)}
              </select></label>
          )}
          <button className="btn-primary" onClick={run} disabled={busy || (scenario !== "purchases_change" && !invoiceId)}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : "Simulate"}</button>
        </div>
        {error && <p role="alert" className="text-sm text-bad mt-3">{error}</p>}
        {w && (
          <div className="mt-5">
            <div className="rounded-xl bg-warn/10 text-warn text-sm px-4 py-2.5 font-semibold">SIMULATION · {w.note}</div>
            <p className="font-semibold mt-3">{w.scenario}</p>
            <p className="text-xs text-ink-faint">{w.assumption}</p>
            {w.status && <p className="text-sm mt-2">ITC status: <b>{w.status.current.replaceAll("_", " ").toLowerCase()}</b> → <b className="text-warn">{w.status.simulated.replaceAll("_", " ").toLowerCase()}</b> (simulated)</p>}
            <div className="overflow-x-auto -mx-3 mt-3"><table className="tbl">
              <thead><tr><th>Metric</th><th className="num">Current (actual)</th><th className="num">Simulated</th><th className="num">Change</th></tr></thead>
              <tbody>{w.rows.map((r) => <tr key={r.metric}><td>{r.metric}</td><td className="num">{inr(r.current)}</td>
                <td className="num font-semibold text-warn">{inr(r.simulated)}</td><td className={`num ${r.change > 0 ? "text-bad" : r.change < 0 ? "text-good" : "text-ink-faint"}`}>{r.change > 0 ? "+" : ""}{inr(r.change)}</td></tr>)}</tbody>
            </table></div>
            {w.simulated_reasons?.length ? <ul className="text-sm text-ink-soft mt-3 list-disc pl-5">{w.simulated_reasons.map((x, i) => <li key={i}>{x}</li>)}</ul> : null}
          </div>
        )}
      </section>
    </div>
  );
}
