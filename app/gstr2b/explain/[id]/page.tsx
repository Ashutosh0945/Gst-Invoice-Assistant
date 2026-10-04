"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, CircleAlert, Mail } from "lucide-react";
import { ai, type Recon2b } from "@/lib/ai";
import { AiNote } from "@/components/AiNote";

export default function Explain2b() {
  const { id } = useParams<{ id: string }>();
  const [r, setR] = useState<Recon2b | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { ai.recon2b(id).then(setR).catch((e) => setError(e.message)); }, [id]);
  if (error) return <div className="pt-10 neu-card p-8 text-center">{error}</div>;
  if (!r) return <div className="pt-8 h-64 neu-card animate-pulse" />;
  return (
    <div className="max-w-3xl">
      <Link href="/gstr2b" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink-strong mt-6"><ArrowLeft className="w-4 h-4" aria-hidden />GSTR-2B match</Link>
      <h1 className="text-[26px] font-extrabold tracking-tight pt-4">Why {r.record.invoice_number} {r.record.match_status === "MATCHED" ? "matches" : "doesn't match"}</h1>
      <p className="text-ink-soft">{r.record.supplier_name} · {r.record.supplier_gstin}</p>
      <section className="neu-card p-5 mt-6"><p className="font-semibold">{r.reason}</p>
        {r.comparison.length > 0 ? (
          <div className="overflow-x-auto -mx-3 mt-3"><table className="tbl"><thead><tr><th>Field</th><th>Your books</th><th>GSTR-2B (vendor reported)</th><th /></tr></thead>
            <tbody>{r.comparison.map((c) => <tr key={c.field} className={c.match ? "" : "bg-bad/5"}><td className="font-semibold">{c.field}</td><td>{String(c.your_books ?? "—")}</td><td>{String(c.gstr2b ?? "—")}</td>
              <td>{c.match ? <CheckCircle2 className="w-4 h-4 text-good" aria-label="matches" /> : <CircleAlert className="w-4 h-4 text-bad" aria-label="differs" />}</td></tr>)}</tbody></table></div>
        ) : <p className="text-sm text-ink-soft mt-2">There's no matching invoice in your books to compare with.</p>}
      </section>
      <div className="mt-6"><AiNote e={r.explanation} title="Explanation" /></div>
      {r.record.matched_invoice_id && <div className="flex gap-2 mt-6">
        <Link href={`/invoices/${r.record.matched_invoice_id}`} className="btn">Open invoice</Link>
        <Link href={`/invoices/${r.record.matched_invoice_id}/message`} className="btn-primary"><Mail className="w-4 h-4" aria-hidden />Draft message to vendor</Link></div>}
    </div>
  );
}
