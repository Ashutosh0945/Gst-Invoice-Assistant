"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, Bot, Loader2 } from "lucide-react";
import { ai, inr, type VendorProfile } from "@/lib/ai";
import { AiNote } from "@/components/AiNote";

export default function VendorPage() {
  const key = decodeURIComponent(useParams<{ key: string }>().key);
  const [v, setV] = useState<VendorProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { ai.vendorProfile(key).then(setV).catch((e) => setError(e.message)); }, [key]);
  if (error) return <div className="pt-10 neu-card p-8 text-center"><p className="font-semibold">Vendor not found</p><p className="text-sm text-ink-soft">{error}</p></div>;
  if (!v) return <div className="pt-8 space-y-3 animate-pulse">{[0, 1, 2].map((i) => <div key={i} className="h-24 neu-card" />)}</div>;
  const p = v.profile;
  const stats: Array<[string, string | number]> = [["Invoices", p.invoice_count], ["Purchase value", inr(p.purchase_value)], ["Average invoice", inr(p.average_invoice_value)],
    ["GST errors", p.gst_errors], ["GSTR-2B mismatches", p.gstr2b_mismatches], ["2B filing rate", p.filing_rate_pct === null ? "—" : `${p.filing_rate_pct}%`],
    ["ITC at risk", inr(p.itc_at_risk)], ["E-invoice problems", p.einvoice_problems]];
  return (
    <div className="max-w-5xl">
      <Link href="/vendors" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink-strong mt-6"><ArrowLeft className="w-4 h-4" aria-hidden />Vendors</Link>
      <header className="pt-4 pb-6 flex flex-wrap justify-between gap-3">
        <div><h1 className="text-[28px] font-extrabold tracking-tight">{p.vendor_name}</h1><p className="text-ink-soft">{p.vendor_gstin || "No GSTIN on record"}</p></div>
        <div className="flex gap-2">
          <button className="btn" disabled={busy} onClick={async () => { setBusy(true); try { setV(await ai.vendorProfile(key, true)); } finally { setBusy(false); } }}>
            {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : null}{v.summary ? "Regenerate summary" : "AI summary"}</button>
          <Link href={`/copilot?q=${encodeURIComponent(`Tell me about vendor ${p.vendor_name}: GST errors and GSTR-2B mismatches`)}`} className="btn-primary"><Bot className="w-4 h-4" aria-hidden />Ask about this vendor</Link>
        </div>
      </header>
      {v.summary && <div className="mb-6"><AiNote e={v.summary} title="Vendor summary" /></div>}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{stats.map(([l, x]) => <div key={l} className="neu-card p-4"><div className="text-xs text-ink-soft">{l}</div><div className="text-lg font-bold tabular">{x}</div></div>)}</div>
      {p.repeated_issues.length > 0 && <section className="neu-card p-5 mt-6"><h2 className="font-bold">Repeated issues</h2>
        <ul className="text-sm mt-2 space-y-1">{p.repeated_issues.map((r) => <li key={r.code}>{r.code.replaceAll("_", " ").toLowerCase()} — {r.times} times</li>)}</ul></section>}
      <section className="neu-card p-5 mt-6"><h2 className="font-bold mb-3">Monthly trend</h2>
        <div className="overflow-x-auto -mx-3"><table className="tbl"><thead><tr><th>Month</th><th className="num">Invoices</th><th className="num">Value</th><th className="num">GST errors</th></tr></thead>
          <tbody>{v.monthly_trend.map((m) => <tr key={m.month}><td>{m.month}</td><td className="num">{m.invoices}</td><td className="num">{inr(m.value)}</td><td className="num">{m.errors}</td></tr>)}</tbody></table></div></section>
      <section className="neu-card p-5 mt-6"><h2 className="font-bold mb-3">Invoices</h2>
        <div className="overflow-x-auto -mx-3"><table className="tbl"><thead><tr><th>Invoice</th><th>Date</th><th className="num">Total</th><th>Status</th><th>GSTR-2B</th><th>Errors</th><th /></tr></thead>
          <tbody>{v.invoices.map((i) => <tr key={i.invoice_id}><td><Link href={`/invoices/${i.invoice_id}`} className="font-semibold hover:text-accent-soft">{i.invoice_number || "—"}</Link></td>
            <td className="text-ink-soft">{i.invoice_date || "—"}</td><td className="num">{inr(i.grand_total)}</td><td className="text-xs">{i.status.replaceAll("_", " ").toLowerCase()}</td>
            <td className="text-xs">{(i.gstr2b_status || "not checked").replaceAll("_", " ").toLowerCase()}</td><td className="text-xs text-bad">{i.errors.join(", ")}</td>
            <td><Link href={`/invoices/${i.invoice_id}/investigate`} className="text-xs text-accent-soft">Investigate</Link></td></tr>)}</tbody></table></div></section>
    </div>
  );
}
