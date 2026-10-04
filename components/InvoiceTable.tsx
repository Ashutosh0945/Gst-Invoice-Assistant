"use client";

import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Columns3, Search } from "lucide-react";
import type { InvoiceSummary } from "@/lib/api";
import { formatDate, formatMoney, formatPercent } from "@/lib/api";
import { EinvBadge, StatusBadge, TwoBBadge } from "@/components/badges";

type Col = "vendor" | "date" | "total" | "confidence" | "gstr2b" | "einvoice" | "status";
const COLS: Array<[Col, string]> = [["vendor", "Vendor"], ["date", "Date"], ["total", "Total"], ["confidence", "Confidence"],
  ["gstr2b", "GSTR-2B"], ["einvoice", "E-invoice"], ["status", "Status"]];
const PAGE = 25;

/** Searchable, sortable, paginated invoice table with column visibility and expandable rows. */
export function InvoiceTable({ rows, action, showAiPreview }: { rows: InvoiceSummary[]; action?: string; showAiPreview?: boolean }) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: Col | "invoice"; dir: 1 | -1 }>({ key: "date", dir: -1 });
  const [page, setPage] = useState(0);
  const [hidden, setHidden] = useState<Set<Col>>(new Set());
  const [showCols, setShowCols] = useState(false);
  const [open, setOpen] = useState<Set<string>>(new Set());

  const sorted = useMemo(() => {
    const t = q.trim().toLowerCase();
    const f = t ? rows.filter((i) => [i.invoice_number, i.vendor_name_raw, i.vendor_gstin_raw, i.source_filename, i.status]
      .some((v) => (v || "").toLowerCase().includes(t))) : rows;
    const val = (i: InvoiceSummary): string | number => ({
      invoice: i.invoice_number || "", vendor: i.vendor_name_raw || "", date: i.invoice_date || "", total: Number(i.grand_total || 0),
      confidence: Number(i.confidence_score || 0), gstr2b: i.gstr2b_status || "", einvoice: i.einvoice_status || "", status: i.status,
    } as Record<string, string | number>)[sort.key];
    return [...f].sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * sort.dir);
  }, [rows, q, sort]);
  const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
  const view = sorted.slice(page * PAGE, page * PAGE + PAGE);
  const on = (c: Col) => !hidden.has(c);
  const Th = ({ k, label, num }: { k: Col | "invoice"; label: string; num?: boolean }) => (
    <th className={num ? "num" : ""} aria-sort={sort.key === k ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
      <button className="inline-flex items-center gap-1 hover:text-ink-strong" onClick={() => setSort({ key: k, dir: sort.key === k ? (sort.dir === 1 ? -1 : 1) : 1 })}>
        {label}{sort.key === k && (sort.dir === 1 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}</button></th>);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <label className="flex items-center gap-2 field py-0 h-10 max-w-xs">
          <Search className="w-4 h-4 text-ink-faint" aria-hidden />
          <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="Filter this table…" aria-label="Filter invoices" className="bg-transparent outline-none flex-1" />
        </label>
        <div className="relative">
          <button className="btn py-2" aria-expanded={showCols} onClick={() => setShowCols((v) => !v)}><Columns3 className="w-4 h-4" aria-hidden />Columns</button>
          {showCols && <div className="absolute z-20 mt-2 neu-card p-3 space-y-1.5 min-w-[160px]">
            {COLS.map(([c, l]) => <label key={c} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={on(c)}
              onChange={() => setHidden((h) => { const n = new Set(h); if (n.has(c)) n.delete(c); else n.add(c); return n; })} />{l}</label>)}</div>}
        </div>
        <span className="text-xs text-ink-faint ml-auto">{sorted.length} invoice{sorted.length === 1 ? "" : "s"}</span>
      </div>
      <div className="overflow-x-auto -mx-3">
        <table className="tbl">
          <thead><tr>
            <th className="w-8"><span className="sr-only">Expand</span></th><Th k="invoice" label="Invoice" />
            {on("vendor") && <Th k="vendor" label="Vendor" />}{on("date") && <Th k="date" label="Date" />}{on("total") && <Th k="total" label="Total" num />}
            {on("confidence") && <Th k="confidence" label="Confidence" num />}{on("gstr2b") && <Th k="gstr2b" label="GSTR-2B" />}
            {on("einvoice") && <Th k="einvoice" label="E-invoice" />}{on("status") && <Th k="status" label="Status" />}{action && <th />}
          </tr></thead>
          <tbody>
            {view.map((i) => (
              <Fragment key={i.id}>
                <tr>
                  <td><button aria-label={open.has(i.id) ? "Collapse row" : "Expand row"} aria-expanded={open.has(i.id)} className="text-ink-faint hover:text-ink-strong"
                    onClick={() => setOpen((o) => { const n = new Set(o); if (n.has(i.id)) n.delete(i.id); else n.add(i.id); return n; })}>
                    {open.has(i.id) ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}</button></td>
                  <td>
                    <Link href={`/invoices/${i.id}`} className="font-semibold hover:text-accent-soft">{i.invoice_number ?? i.source_filename}</Link>
                    {showAiPreview && i.llm_explanation && (
                      <div className="flex items-start gap-1 mt-1 max-w-[280px]">
                        <span className="text-accent-soft shrink-0" title="AI summary">✦</span>
                        <p className="text-xs text-ink-faint line-clamp-2">{i.llm_explanation}</p>
                      </div>)}
                  </td>
                  {on("vendor") && <td><div className="text-ink truncate max-w-[220px]">{i.vendor_name_raw ?? "—"}</div><div className="text-xs text-ink-faint">{i.vendor_gstin_raw ?? ""}</div></td>}
                  {on("date") && <td className="text-ink-soft whitespace-nowrap">{formatDate(i.invoice_date)}</td>}
                  {on("total") && <td className="num font-medium">{formatMoney(i.grand_total)}</td>}
                  {on("confidence") && <td className="num text-ink-soft">{formatPercent(i.confidence_score)}</td>}
                  {on("gstr2b") && <td><TwoBBadge value={i.gstr2b_status} /></td>}
                  {on("einvoice") && <td><EinvBadge value={i.einvoice_status} /></td>}
                  {on("status") && <td><StatusBadge value={i.status} /></td>}
                  {action && <td className="text-right"><Link href={`/invoices/${i.id}`} className="btn py-1.5">{action}</Link></td>}
                </tr>
                {open.has(i.id) && (
                  <tr><td /><td colSpan={9} className="text-sm">
                    <div className="flex flex-wrap gap-x-6 gap-y-1 text-ink-soft">
                      <span>File: <b className="text-ink">{i.source_filename}</b></span>
                      <span>Added: {formatDate(i.created_at)}</span>
                      {i.vendor_gstin_raw && <Link href={`/vendors/${encodeURIComponent(i.vendor_gstin_raw)}`} className="text-accent-soft">Vendor profile</Link>}
                      <Link href={`/invoices/${i.id}/investigate`} className="text-accent-soft">Investigate</Link>
                      <Link href={`/invoices/${i.id}/message`} className="text-accent-soft">Message vendor</Link>
                    </div>
                    {i.llm_explanation && <p className="text-xs text-ink-faint mt-1.5">✦ {i.llm_explanation}</p>}
                  </td></tr>)}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <nav className="flex items-center justify-end gap-2 mt-3 text-sm" aria-label="Pagination">
          <button className="btn py-1.5" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
          <span className="text-ink-soft">Page {page + 1} of {pages}</span>
          <button className="btn py-1.5" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next</button>
        </nav>)}
    </div>
  );
}
