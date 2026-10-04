"use client";

import Link from "next/link";
import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { ai, inr, type SearchResult } from "@/lib/ai";

export function SmartSearch() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function go(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true); setError(null);
    try { setRes(await ai.search(q)); } catch (err) { setError(err instanceof Error ? err.message : "Search failed"); } finally { setBusy(false); }
  }
  return (
    <section className="neu-card p-5 mb-6">
      <form onSubmit={go} className="flex flex-col sm:flex-row gap-2">
        <label className="flex items-center gap-2 field py-0 h-12 flex-1">
          <Sparkles className="w-4 h-4 text-accent-soft" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} className="bg-transparent outline-none flex-1"
            placeholder="Smart search, e.g. “invoices above 50,000 from vendors with GSTR-2B mismatches”" aria-label="Smart search in plain English" />
        </label>
        <button className="btn-primary h-12" disabled={busy}>{busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : "Search"}</button>
      </form>
      {error && <p role="alert" className="text-sm text-bad mt-3">{error}</p>}
      {res && (
        <div className="mt-4">
          <p className="text-sm text-ink-soft">
            {res.note ? res.note : <>Understood as: <b className="text-ink">{res.understood_as.join(" · ")}</b> — {res.count} invoice{res.count === 1 ? "" : "s"}</>}
            {res.understood_by !== "rules" && <span className="text-ink-faint"> (filters suggested by AI and checked against an allowed list)</span>}
            <button className="ml-3 text-accent-soft" onClick={() => setRes(null)}>Clear</button>
          </p>
          {res.results.length > 0 && (
            <div className="overflow-x-auto -mx-3 mt-3"><table className="tbl">
              <thead><tr><th>Invoice</th><th>Vendor</th><th>Date</th><th className="num">Total</th><th>Status</th><th /></tr></thead>
              <tbody>{res.results.map((r) => (
                <tr key={r.invoice_id}><td><Link href={`/invoices/${r.invoice_id}`} className="font-semibold hover:text-accent-soft">{r.invoice_number || "—"}</Link></td>
                  <td className="text-ink-soft">{r.vendor}</td><td className="text-ink-soft">{r.invoice_date || "—"}</td>
                  <td className="num">{inr(r.grand_total)}</td><td className="text-xs">{r.status.replaceAll("_", " ").toLowerCase()}</td>
                  <td><Link href={`/invoices/${r.invoice_id}/investigate`} className="text-xs text-accent-soft">Investigate</Link></td></tr>))}</tbody>
            </table></div>
          )}
        </div>
      )}
    </section>
  );
}
