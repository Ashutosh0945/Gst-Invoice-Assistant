"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, Lightbulb, MessagesSquare, Trash2, XCircle } from "lucide-react";
import { app, fmtDate, inr, type BillDetail } from "@/lib/client";
import { Card, Empty, ErrorNote } from "@/components/ui";

const TONE = { good: ["text-good", CheckCircle2], warn: ["text-warn", AlertTriangle], bad: ["text-bad", XCircle] } as const;

export default function BillPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [b, setB] = useState<BillDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);
  useEffect(() => { app.bill(id).then(setB).catch((e) => setError(e.message)); }, [id]);

  async function patch(body: Record<string, unknown>) {
    setSaving(true);
    try { setB(await app.updateBill(id, body)); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "Couldn't save."); } finally { setSaving(false); }
  }

  if (error && !b) return <div className="pt-10"><Card><Empty title="Bill not found" hint={error} action={<Link href="/app/bills" className="btn">Back to bills</Link>} /></Card></div>;
  if (!b) return <p className="pt-10 text-ink-soft">Loading…</p>;
  const [toneCls, ToneIcon] = TONE[b.insights.tone];

  return (
    <div>
      <Link href="/app/bills" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-white mt-6"><ArrowLeft className="w-4 h-4" aria-hidden /> Bills</Link>
      <header className="pt-4 pb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-extrabold tracking-tight">{b.vendor || b.file}</h1>
          <p className="text-ink-soft">{fmtDate(b.date)}{b.invoice_number ? ` · Bill ${b.invoice_number}` : ""}</p>
        </div>
        <div className="text-3xl font-extrabold tabular">{inr(b.total, true)}</div>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6 min-w-0">
          <section className="neu-card p-6 rise">
            <div className="flex items-start gap-4">
              <div className="icon-tile shrink-0"><ToneIcon className={`w-6 h-6 ${toneCls}`} aria-hidden /></div>
              <div>
                <h2 className={`text-xl font-extrabold ${toneCls}`}>{b.insights.headline}</h2>
                {b.insights.problems.length > 0 && (
                  <ul className="mt-3 space-y-1.5 text-sm">{b.insights.problems.map((p, i) => <li key={i}>• {p}</li>)}</ul>
                )}
              </div>
            </div>
            {b.insights.tips.length > 0 && (
              <ul className="mt-5 space-y-2">
                {b.insights.tips.map((t, i) => (
                  <li key={i} className="flex gap-2.5 text-sm neu-inset px-4 py-3"><Lightbulb className="w-4 h-4 text-warn shrink-0 mt-0.5" aria-hidden />{t}</li>
                ))}
              </ul>
            )}
            <Link href="/app/assistant" className="btn mt-5"><MessagesSquare className="w-4 h-4" aria-hidden />Ask about this bill</Link>
          </section>

          <Card title="What's on the bill">
            {b.items.length === 0 ? <p className="text-sm text-ink-soft">We couldn&apos;t read the item lines from this file.</p> : (
              <div className="overflow-x-auto -mx-3">
                <table className="tbl">
                  <thead><tr><th>Item</th><th>HSN/SAC</th><th className="num">Qty</th><th className="num">GST</th><th className="num">Amount</th></tr></thead>
                  <tbody>{b.items.map((li) => (
                    <tr key={li.line_no}><td>{li.description ?? "—"}</td><td className="text-ink-soft">{li.hsn_sac ?? "—"}</td>
                      <td className="num">{li.quantity ?? "—"}</td><td className="num">{li.gst_rate ? `${li.gst_rate}%` : "—"}</td><td className="num">{inr(li.amount, true)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            )}
            <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
              {[["Before tax", b.subtotal], ["GST paid", b.insights.gst_paid], ["Total", b.total], ...(b.insights.gst_claimable !== null ? [["GST you can claim", b.insights.gst_claimable]] : [])].map(([l, v]) => (
                <div key={l as string} className="neu-inset p-3"><dt className="text-xs text-ink-soft">{l}</dt><dd className="font-bold tabular">{inr(v as string, true)}</dd></div>
              ))}
            </dl>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title="Organise">
            <label className="block"><span className="text-sm text-ink-soft">Category</span>
              <select className="field mt-1.5" value={b.category} disabled={saving} onChange={(e) => patch({ category: e.target.value })}>
                {Object.entries(b.categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select></label>
            <label className="block mt-4"><span className="text-sm text-ink-soft">Warranty until</span>
              <input type="date" className="field mt-1.5" value={b.warranty_until ?? ""} disabled={saving}
                onChange={(e) => patch(e.target.value ? { warranty_until: e.target.value } : { clear_warranty: true })} /></label>
            <p className="text-xs text-ink-faint mt-1.5">We&apos;ll remind you on the home screen 60 days before it ends.</p>
            <NoteField initial={b.note ?? ""} onSave={(note) => patch({ note })} />
            {error && <ErrorNote>{error}</ErrorNote>}
          </Card>
          <Card title="File">
            <p className="text-sm text-ink-soft break-all">{b.file}</p>
            {b.vendor_gstin && <p className="text-sm mt-2">Seller GSTIN <span className="text-ink-soft">{b.vendor_gstin}</span></p>}
            {!confirmDel ? (
              <button className="btn mt-4 text-bad" onClick={() => setConfirmDel(true)}><Trash2 className="w-4 h-4" aria-hidden />Delete bill</button>
            ) : (
              <div className="flex gap-2 mt-4 items-center text-sm">Delete for good?
                <button className="btn py-1.5 text-bad" onClick={async () => { await app.deleteBill(id); router.replace("/app/bills"); }}>Delete</button>
                <button className="btn py-1.5" onClick={() => setConfirmDel(false)}>Keep</button>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function NoteField({ initial, onSave }: { initial: string; onSave: (n: string) => void }) {
  const [v, setV] = useState(initial);
  return (
    <label className="block mt-4"><span className="text-sm text-ink-soft">Note</span>
      <textarea className="field mt-1.5" rows={2} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== initial && onSave(v)}
        placeholder="e.g. Office chair for home desk" /></label>
  );
}
