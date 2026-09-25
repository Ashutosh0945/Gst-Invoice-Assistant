"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Receipt, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { app, fmtDate, inr, type BillRow } from "@/lib/client";
import { Card, Empty } from "@/components/ui";
import { BillUpload } from "@/components/BillUpload";

const CATS: Array<[string, string]> = [["", "All"], ["food", "Food"], ["travel", "Travel"], ["health", "Health"],
  ["electronics", "Electronics"], ["office", "Office"], ["professional", "Services"], ["utilities", "Utilities"], ["other", "Other"]];

export default function Bills() {
  const [rows, setRows] = useState<BillRow[] | null>(null);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => app.bills(q, cat).then(setRows).catch((e) => setError(e.message)), 200);
    return () => clearTimeout(t);
  }, [q, cat]);

  return (
    <div>
      <header className="pt-8 pb-6">
        <h1 className="text-[28px] font-extrabold tracking-tight">Your bills</h1>
        <p className="text-ink-soft mt-1">Every bill checked for wrong GST, bad maths and duplicates — and kept safe for warranty and tax time.</p>
      </header>
      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <Card>
          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <label className="flex items-center gap-2 field py-0 h-11 flex-1">
              <Search className="w-4 h-4 text-ink-faint" aria-hidden />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search shop, item, category…" aria-label="Search bills" className="bg-transparent outline-none flex-1" />
            </label>
          </div>
          <div className="flex gap-2 overflow-x-auto pb-3 mb-2">
            {CATS.map(([v, l]) => (
              <button key={v || "all"} onClick={() => setCat(v)} aria-pressed={cat === v}
                className={`shrink-0 px-3.5 py-1.5 rounded-xl text-sm ${cat === v ? "bg-base shadow-neu-in text-white" : "bg-base shadow-neu-sm text-ink-soft"}`}>{l}</button>
            ))}
          </div>
          {error ? <Empty title="Couldn't load bills" hint={error} /> : rows === null ? <p className="text-ink-soft text-sm py-6">Loading…</p> :
            rows.length === 0 ? <Empty title={q || cat ? "No bills match" : "No bills yet"} hint={q || cat ? "Try another search." : "Add your first bill with the panel on the right."} /> : (
              <ul className="space-y-3">
                {rows.map((b) => (
                  <li key={b.id}>
                    <Link href={`/app/bills/${b.id}`} className="flex items-center gap-3 neu-tile p-3.5 hover:text-white">
                      <div className="icon-tile w-10 h-10 shrink-0">
                        {b.einvoice_status === "MISMATCH" || b.einvoice_status === "SIGNATURE_INVALID"
                          ? <ShieldAlert className="w-4 h-4 text-bad" aria-label="QR problem" />
                          : b.einvoice_status === "VERIFIED" ? <ShieldCheck className="w-4 h-4 text-good" aria-label="Verified e-invoice" />
                          : <Receipt className="w-4 h-4 text-accent-soft" aria-hidden />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold truncate">{b.vendor || b.file}</div>
                        <div className="text-xs text-ink-soft">{b.category_label} · {fmtDate(b.date)}{b.warranty_until ? ` · warranty to ${fmtDate(b.warranty_until)}` : ""}</div>
                      </div>
                      <div className="font-bold tabular">{inr(b.total)}</div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
        </Card>
        <div className="xl:sticky xl:top-8 self-start"><Card title="Add a bill"><BillUpload /></Card></div>
      </div>
    </div>
  );
}
