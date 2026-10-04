"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertOctagon, AlertTriangle, Eye, MessageSquareText, RefreshCw, Search } from "lucide-react";
import { ai, inr, type Anomaly, type RiskItem } from "@/lib/ai";

const SEV: Record<string, { cls: string; icon: typeof AlertOctagon }> = {
  Critical: { cls: "text-bad bg-bad/10", icon: AlertOctagon },
  High: { cls: "text-warn bg-warn/10", icon: AlertTriangle },
  Review: { cls: "text-info bg-info/10", icon: Eye },
};

export default function RiskCenter() {
  const [data, setData] = useState<{ items: RiskItem[]; counts: Record<string, number> } | null>(null);
  const [an, setAn] = useState<{ items: Anomaly[]; note: string; vendors_with_insufficient_history: number } | null>(null);
  const [tab, setTab] = useState<"issues" | "anomalies">("issues");
  const [sev, setSev] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const load = () => {
    setError(null); setData(null);
    ai.risks().then(setData).catch((e) => setError(e.message));
    ai.anomalies().then(setAn).catch(() => undefined);
  };
  useEffect(load, []);
  const items = (data?.items || []).filter((x) => !sev || x.severity === sev);

  return (
    <div>
      <header className="pt-8 pb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">What needs your attention?</h1>
          <p className="text-ink-soft mt-1">Every item comes from an actual check in the system: validation, GSTR-2B, ITC, e-invoice, PO and anomaly detection.</p>
        </div>
        <button className="btn" onClick={load}><RefreshCw className="w-4 h-4" aria-hidden />Run risk analysis</button>
      </header>

      <div className="grid grid-cols-3 gap-4 mb-6">
        {(["Critical", "High", "Review"] as const).map((s) => {
          const Icon = SEV[s].icon;
          return (
            <button key={s} onClick={() => { setSev(sev === s ? "" : s); setTab("issues"); }} aria-pressed={sev === s}
              className={`neu-card p-5 text-left transition hover:-translate-y-0.5 ${sev === s ? "ring-2 ring-accent/60" : ""}`}>
              <Icon className={`w-5 h-5 ${SEV[s].cls.split(" ")[0]}`} aria-hidden />
              <div className="text-3xl font-extrabold tabular mt-3">{data ? data.counts[s] ?? 0 : "–"}</div>
              <div className="text-sm text-ink-soft">{s}</div>
            </button>
          );
        })}
      </div>

      <div className="flex gap-2 mb-4" role="tablist">
        {([["issues", "Issues"], ["anomalies", `Unusual invoices${an ? ` (${an.items.length})` : ""}`]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`px-4 py-2 rounded-xl text-sm ${tab === k ? "bg-base shadow-neu-in text-ink-strong" : "bg-base shadow-neu-sm text-ink-soft"}`}>{l}</button>
        ))}
      </div>

      {error && <div role="alert" className="neu-card p-5 text-bad">{error} <button className="underline ml-2" onClick={load}>Retry</button></div>}
      {!data && !error && <div className="space-y-3 animate-pulse">{[0, 1, 2, 3].map((i) => <div key={i} className="h-20 neu-card" />)}</div>}

      {data && tab === "issues" && (items.length === 0
        ? <div className="neu-card p-10 text-center"><p className="font-semibold">Nothing {sev ? `${sev.toLowerCase()} ` : ""}needs your attention.</p></div>
        : <ul className="space-y-3">{items.map((x) => {
            const Icon = SEV[x.severity].icon;
            return (
              <li key={x.key} className="neu-card p-4 md:p-5">
                <div className="flex flex-wrap items-start gap-3">
                  <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold ${SEV[x.severity].cls}`}><Icon className="w-3.5 h-3.5" aria-hidden />{x.severity}</span>
                  <span className="text-xs text-ink-faint pt-1">{x.category}</span>
                  <div className="flex-1 min-w-[220px]">
                    <div className="font-semibold">{x.title}</div>
                    <div className="text-sm text-ink-soft mt-0.5">{x.reason}</div>
                    <div className="text-sm mt-2"><span className="text-ink-faint">Next step: </span>{x.next_action}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">{x.invoice_number || x.vendor || "—"}</div>
                    {x.amount_at_stake !== null && <div className="text-sm tabular text-ink-soft">{inr(x.amount_at_stake)} at stake</div>}
                  </div>
                </div>
                {x.invoice_id && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    <Link href={`/invoices/${x.invoice_id}`} className="btn py-1.5"><Eye className="w-4 h-4" aria-hidden />View</Link>
                    <Link href={`/invoices/${x.invoice_id}/investigate`} className="btn py-1.5"><Search className="w-4 h-4" aria-hidden />Investigate</Link>
                    <Link href={`/invoices/${x.invoice_id}/investigate?explain=1`} className="btn py-1.5"><MessageSquareText className="w-4 h-4" aria-hidden />Explain</Link>
                  </div>
                )}
              </li>
            );
          })}</ul>)}

      {tab === "anomalies" && an && (
        <div className="neu-card p-5">
          <p className="text-sm text-ink-soft mb-4">{an.note}{an.vendors_with_insufficient_history ? ` ${an.vendors_with_insufficient_history} vendor(s) don't have enough history yet.` : ""}</p>
          {an.items.length === 0 ? <p className="font-semibold text-center py-6">Nothing unusual found.</p> : (
            <div className="overflow-x-auto -mx-3"><table className="tbl">
              <thead><tr><th>Invoice</th><th>Vendor</th><th>Indicator</th><th>Why</th><th className="num">Risk score</th></tr></thead>
              <tbody>{an.items.map((x, i) => (
                <tr key={i}><td><Link className="font-semibold hover:text-accent-soft" href={`/invoices/${x.invoice_id}/investigate`}>{x.invoice_number || "—"}</Link></td>
                  <td className="text-ink-soft">{x.vendor}</td><td>{x.kind.replaceAll("_", " ")}</td><td className="text-ink-soft text-sm max-w-md">{x.reason}</td>
                  <td className="num font-semibold">{x.score}</td></tr>))}</tbody>
            </table></div>
          )}
        </div>
      )}
    </div>
  );
}
