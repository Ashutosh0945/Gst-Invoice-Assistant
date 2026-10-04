"use client";

import Link from "next/link";
import { useState } from "react";
import { Download, FileText, Loader2, Printer } from "lucide-react";
import { ai, inr, type Report } from "@/lib/ai";
import { AiNote } from "@/components/AiNote";

const PERIODS: Array<[string, string]> = [["this_month", "This month"], ["last_month", "Last month"], ["this_quarter", "This quarter"], ["this_fy", "This FY"], ["all", "All time"]];

function csv(rows: Array<Record<string, unknown>>, name: string) {
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? "").replaceAll('"', '""')}"`;
  const blob = new Blob([[cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n")], { type: "text/csv" });
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
  a.click(); URL.revokeObjectURL(a.href);
}

export default function Reports() {
  const [kind, setKind] = useState<"monthly" | "audit">("monthly");
  const [period, setPeriod] = useState("this_month");
  const [month, setMonth] = useState("");
  const [r, setR] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const gen = async () => {
    setBusy(true); setError(null);
    try { setR(await ai.report(kind, month || period)); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setBusy(false); }
  };
  const f = r?.facts;
  const rk = r?.kind ?? kind;   // render according to the report actually received, not the selected tab
  const H = ({ n, t }: { n: number; t: string }) => <h2 className="text-lg font-bold mt-8 mb-3 break-after-avoid">{rk === "audit" ? `${n}. ` : ""}{t}</h2>;

  return (
    <div className="max-w-5xl">
      <header className="pt-8 pb-6 print:hidden">
        <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">Reports</h1>
        <p className="text-ink-soft mt-1">Every figure is calculated from your records; AI commentary is marked separately and every finding links to its invoice.</p>
      </header>
      <section className="neu-card p-5 print:hidden">
        <div className="flex flex-wrap gap-3 items-end">
          <div className="flex gap-1 p-1 rounded-xl bg-base-deep shadow-neu-in" role="radiogroup" aria-label="Report type">
            {([["monthly", "Monthly GST report"], ["audit", "Audit report"]] as const).map(([k, l]) => (
              <button key={k} role="radio" aria-checked={kind === k} onClick={() => { setKind(k); setR(null); }}
                className={`px-3.5 py-2 rounded-lg text-sm ${kind === k ? "bg-base shadow-neu-sm text-ink-strong" : "text-ink-soft"}`}>{l}</button>))}
          </div>
          <label><span className="text-xs text-ink-soft">Period</span>
            <select className="field mt-1" value={period} onChange={(e) => { setPeriod(e.target.value); setMonth(""); }}>
              {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label><span className="text-xs text-ink-soft">or a specific month</span>
            <input type="month" className="field mt-1" value={month} onChange={(e) => setMonth(e.target.value)} /></label>
          <button className="btn-primary" onClick={gen} disabled={busy}>{busy ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Generating…</> : <><FileText className="w-4 h-4" aria-hidden />Generate</>}</button>
        </div>
        {error && <p role="alert" className="text-sm text-bad mt-3">{error}</p>}
      </section>

      {r && f && (
        <article className="neu-card p-6 md:p-8 mt-6 print:shadow-none print:bg-white print:text-black">
          <div className="flex flex-wrap justify-between gap-3">
            <div>
              <h1 className="text-2xl font-extrabold">{rk === "audit" ? "GST Audit Report" : "Monthly GST Report"} · {f.period.label}</h1>
              <p className="text-xs text-ink-faint">Generated {new Date(r.generated_at).toLocaleString("en-IN")} · GST Desk</p>
            </div>
            <div className="flex gap-2 print:hidden">
              <button className="btn py-1.5" onClick={() => window.print()}><Printer className="w-4 h-4" aria-hidden />Print / PDF</button>
              <button className="btn py-1.5" onClick={() => csv(f.detailed_findings, "findings.csv")}><Download className="w-4 h-4" aria-hidden />Findings CSV</button>
              <button className="btn py-1.5" onClick={() => csv(f.review_items as unknown as Array<Record<string, unknown>>, "review-items.csv")}><Download className="w-4 h-4" aria-hidden />Issues CSV</button>
            </div>
          </div>
          <H n={1} t={rk === "audit" ? "Executive summary" : "Summary"} />
          {(rk === "audit" ? r.executive_summary : r.summary) && <AiNote e={(rk === "audit" ? r.executive_summary : r.summary)!} title={rk === "audit" ? "Executive summary" : "Summary"} />}
          <H n={2} t="Invoice processing" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <Stat l="Invoices" v={f.processing.invoices} /><Stat l="Avg. read confidence" v={f.processing.average_confidence_pct === null ? "—" : `${f.processing.average_confidence_pct}%`} />
            {Object.entries(f.processing.status_counts).map(([s, n]) => <Stat key={s} l={s.replaceAll("_", " ").toLowerCase()} v={n} />)}
          </div>
          <H n={3} t={rk === "audit" ? "GST validation" : "GST"} />
          <div className="grid grid-cols-2 gap-3 text-sm mb-3"><Stat l="Purchase value" v={inr(f.gst.purchase_value)} /><Stat l="GST amount" v={inr(f.gst.gst_amount)} /></div>
          <Table cols={["GST rate", "Taxable value", "GST", "Lines"]} rows={f.gst.by_rate.map((b) => [b.rate, inr(b.taxable), inr(b.gst), b.lines])} />
          {rk === "audit" && <>
            <p className="text-sm mt-3">{f.validation.error_findings} validation errors. Most frequent: {Object.entries(f.validation.by_code).map(([c, n]) => `${c} (${n})`).join(", ") || "none"}.</p></>}
          <H n={4} t="GSTR-2B reconciliation" />
          {f.gstr2b.imported ? <p className="text-sm">{f.gstr2b.records} records compared · {Object.entries(f.gstr2b.by_status).map(([s, n]) => `${s.replaceAll("_", " ").toLowerCase()}: ${n}`).join(" · ")} · missing from GSTR-2B: {f.gstr2b.missing_in_2b}</p>
            : <p className="text-sm text-ink-soft">No GSTR-2B imported for this period.</p>}
          <H n={5} t={rk === "audit" ? "ITC review" : "Input tax credit"} />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <Stat l="Total ITC" v={inr(f.itc.itc_total)} /><Stat l="Claimable" v={inr(f.itc.itc_eligible)} /><Stat l="At risk" v={inr(f.itc.itc_at_risk)} /><Stat l="Blocked" v={inr(f.itc.itc_blocked)} /></div>
          <H n={6} t="Vendor findings" />
          {f.vendors.length ? <Table cols={["Vendor", "Invoices", "Value", "GST errors", "2B mismatches", "ITC at risk"]}
            rows={f.vendors.map((v) => [v.vendor_name, v.invoice_count, inr(v.purchase_value), v.gst_errors, v.gstr2b_mismatches, inr(v.itc_at_risk)])} /> : <p className="text-sm text-ink-soft">No vendor issues.</p>}
          <H n={7} t="Anomaly findings (risk indicators, not proof of fraud)" />
          {f.anomalies.length ? <Table cols={["Invoice", "Vendor", "Indicator", "Score"]} links={f.anomalies.map((a) => `/invoices/${a.invoice_id}`)}
            rows={f.anomalies.map((a) => [a.invoice_number, a.vendor, a.reason, a.score])} /> : <p className="text-sm text-ink-soft">Nothing unusual.</p>}
          <H n={8} t={rk === "audit" ? "Important issues" : "Items needing review"} />
          {f.review_items.length ? <Table cols={["Severity", "Issue", "Invoice / vendor", "At stake"]} links={f.review_items.map((x) => x.invoice_id ? `/invoices/${x.invoice_id}` : "")}
            rows={f.review_items.map((x) => [x.severity, x.title, x.invoice_number || x.vendor, x.amount_at_stake === null ? "—" : inr(x.amount_at_stake)])} /> : <p className="text-sm text-ink-soft">None.</p>}
          {rk === "audit" && <><H n={9} t="Detailed findings" />
            <Table cols={["Invoice", "Vendor", "Code", "Finding"]} links={f.detailed_findings.map((d) => `/invoices/${d.invoice_id}`)}
              rows={f.detailed_findings.map((d) => [d.invoice_number, d.vendor, d.code, d.message])} /></>}
          {rk === "monthly" && <><H n={9} t="Trend (last months)" />
            <Table cols={["Month", "Invoices", "Purchases", "GST"]} rows={f.trend.map((t) => [t.month, t.invoices, inr(t.purchase_value), inr(t.gst)])} /></>}
        </article>
      )}
    </div>
  );
}

function Stat({ l, v }: { l: string; v: string | number }) {
  return <div className="neu-inset p-3 print:border print:border-gray-300"><div className="text-xs text-ink-soft capitalize">{l}</div><div className="font-bold tabular">{v}</div></div>;
}
function Table({ cols, rows, links }: { cols: string[]; rows: Array<Array<string | number | null>>; links?: string[] }) {
  return (
    <div className="overflow-x-auto -mx-3"><table className="tbl">
      <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j === 0 ? "font-semibold" : ""}>
        {j === 0 && links?.[i] ? <Link href={links[i]} className="hover:text-accent-soft">{c ?? "—"}</Link> : c ?? "—"}</td>)}</tr>)}</tbody>
    </table></div>
  );
}
