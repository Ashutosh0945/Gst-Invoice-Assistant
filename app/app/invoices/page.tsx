"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CheckCircle2, Download, FilePlus2, RotateCcw, Trash2 } from "lucide-react";
import { app, fmtDate, inr, type SalesInvoice } from "@/lib/client";
import { Card, Empty, Kpi } from "@/components/ui";
import { HandCoins, Hourglass, Wallet } from "lucide-react";

export default function Invoices() {
  const [rows, setRows] = useState<SalesInvoice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => app.invoices().then(setRows).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  const unpaid = (rows ?? []).filter((r) => r.status !== "PAID");
  const overdue = unpaid.filter((r) => r.days_overdue > 0);
  const paidThisMonth = (rows ?? []).filter((r) => r.paid_on && r.paid_on.slice(0, 7) === new Date().toISOString().slice(0, 7));
  const sum = (l: SalesInvoice[]) => l.reduce((s, r) => s + Number(r.total), 0);

  async function act(p: Promise<unknown>) {
    try { await p; await load(); } catch (e) { setError(e instanceof Error ? e.message : "That didn't work."); }
  }

  return (
    <div>
      <header className="pt-8 pb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-extrabold tracking-tight">Invoices you send</h1>
          <p className="text-ink-soft mt-1">GST-correct invoices in seconds, and a clear view of who owes you.</p>
        </div>
        <Link href="/app/invoices/new" className="btn-primary"><FilePlus2 className="w-4 h-4" aria-hidden />New invoice</Link>
      </header>

      <div className="grid gap-5 grid-cols-1 sm:grid-cols-3 mb-6">
        <Kpi icon={HandCoins} tone="warn" label="Owed to you" value={inr(sum(unpaid))} pill={`${unpaid.length} unpaid`} />
        <Kpi icon={Hourglass} tone={overdue.length ? "bad" : "good"} label="Overdue" value={inr(sum(overdue))} pill={`${overdue.length} late`} />
        <Kpi icon={Wallet} tone="good" label="Received this month" value={inr(sum(paidThisMonth))} />
      </div>

      <Card>
        {error && <p role="alert" className="text-sm text-bad mb-3">{error}</p>}
        {rows === null ? <p className="text-ink-soft text-sm">Loading…</p> : rows.length === 0 ? (
          <Empty title="No invoices yet" hint="Create one in under a minute. GST is worked out for you." action={<Link href="/app/invoices/new" className="btn-primary">Create your first invoice</Link>} />
        ) : (
          <div className="overflow-x-auto -mx-3">
            <table className="tbl">
              <thead><tr><th>Invoice</th><th>Client</th><th>Due</th><th className="num">Amount</th><th>Status</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td className="font-semibold whitespace-nowrap">{r.number}<div className="text-xs text-ink-faint font-normal">{fmtDate(r.issue_date)}</div></td>
                    <td>{r.client_name}</td>
                    <td className="whitespace-nowrap text-ink-soft">{fmtDate(r.due_date)}</td>
                    <td className="num font-semibold">{inr(r.total, true)}</td>
                    <td>
                      {r.status === "PAID" ? <span className="text-good text-sm font-semibold">Paid {fmtDate(r.paid_on)}</span>
                        : r.days_overdue ? <span className="text-bad text-sm font-semibold">{r.days_overdue} days late</span>
                        : <span className="text-warn text-sm font-semibold">Awaiting payment</span>}
                    </td>
                    <td className="text-right whitespace-nowrap">
                      <a href={`/api/v1/app/invoices/${r.id}/pdf`} className="btn py-1.5 px-2.5" aria-label={`Download ${r.number} as PDF`}><Download className="w-4 h-4" /></a>{" "}
                      {r.status === "PAID"
                        ? <button className="btn py-1.5 px-2.5" aria-label="Mark as unpaid" onClick={() => act(app.markPaid(r.id, null))}><RotateCcw className="w-4 h-4" /></button>
                        : <button className="btn py-1.5" onClick={() => act(app.markPaid(r.id))}><CheckCircle2 className="w-4 h-4 text-good" aria-hidden />Paid</button>}{" "}
                      <button className="btn py-1.5 px-2.5" aria-label={`Delete ${r.number}`} onClick={() => { if (confirm(`Delete ${r.number}?`)) act(app.deleteInvoice(r.id)); }}><Trash2 className="w-4 h-4" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
