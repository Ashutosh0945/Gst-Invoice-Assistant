import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, CheckCircle2, CircleAlert, CircleHelp, Sparkles } from "lucide-react";
import { api, formatDate, formatMoney, formatPercent, type InvoiceDetail } from "@/lib/api";
import { Card, PageHeader } from "@/components/ui";
import { EinvBadge, ItcBadge, SeverityDot, StatusBadge, TwoBBadge } from "@/components/badges";
import { ReviewActions } from "@/components/ReviewActions";
import { PaymentForm } from "@/components/PaymentForm";

export const dynamic = "force-dynamic";

export default async function InvoiceDetailPage({ params }: { params: { id: string } }) {
  let inv: InvoiceDetail;
  try {
    inv = await api.getInvoice(params.id);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.startsWith("404")) notFound();          // the invoice really doesn't exist
    return <LoadError message={msg} />;              // anything else: say what went wrong
  }
  const itc = inv.itc;

  return (
    <div>
      <Link href="/invoices" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-white mt-6">
        <ArrowLeft className="w-4 h-4" aria-hidden /> All invoices
      </Link>
      <PageHeader title={inv.invoice_number || inv.source_filename}
        subtitle={`${inv.vendor_name_raw ?? "Unknown vendor"} · ${formatDate(inv.invoice_date)}`}
        right={<StatusBadge value={inv.status} />} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[["Grand total", formatMoney(inv.grand_total)], ["Taxable value", formatMoney(inv.subtotal)],
          ["GST charged", formatMoney(String(["total_cgst", "total_sgst", "total_igst"].reduce((s, k) =>
            s + Number((inv as unknown as Record<string, string | null>)[k] ?? 0), 0)))],
          ["Read confidence", formatPercent(inv.confidence_score, 1)],
          ["Vendor GSTIN", inv.vendor_gstin_raw ?? "—"]].map(([l, v]) => (
          <div key={l} className="neu-tile p-4">
            <div className="text-xs text-ink-soft">{l}</div>
            <div className="text-lg font-bold tabular mt-1 truncate">{v}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_360px] mt-6">
        <div className="space-y-6 min-w-0">
          <Card title="Input tax credit" action={<ItcBadge value={itc?.status} />}>
            {itc ? (
              <>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  {[["Claimable", itc.eligible_itc, "text-good"], ["Needs decision", itc.review_itc, "text-warn"],
                    ["At risk", itc.at_risk_itc, "text-bad"], ["Blocked", itc.blocked_itc, "text-ink-soft"]].map(([l, v, c]) => (
                    <div key={l} className="neu-inset p-3.5">
                      <div className="text-xs text-ink-soft">{l}</div>
                      <div className={`font-bold tabular mt-0.5 ${c}`}>{formatMoney(v)}</div>
                    </div>
                  ))}
                </div>
                <ul className="mt-5 space-y-2.5">
                  {(itc.reasons ?? []).map((r, i) => (
                    <li key={i} className="flex gap-2.5 text-sm">
                      <span className="mt-1.5"><SeverityDot severity={r.severity} /></span><span>{r.message}</span>
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-ink-soft mt-4">
                  <span>GSTR-2B: <TwoBBadge value={inv.gstr2b_status} /></span>
                  <span>Pay vendor by <b className="text-ink">{formatDate(itc.payment_due_by)}</b></span>
                  <span>Claim by <b className="text-ink">{formatDate(itc.claim_deadline)}</b></span>
                </div>
              </>
            ) : <p className="text-ink-soft text-sm">Credit has not been assessed for this invoice.</p>}
          </Card>

          <Card title="Line items">
            {inv.items.length === 0 ? <p className="text-sm text-ink-soft">No line items were read from this invoice.</p> : (
              <div className="overflow-x-auto -mx-3">
                <table className="tbl">
                  <thead><tr><th>#</th><th>Description</th><th>HSN/SAC</th><th className="num">Qty</th>
                    <th className="num">Rate</th><th className="num">Taxable</th><th className="num">GST %</th><th className="num">Total</th></tr></thead>
                  <tbody>
                    {inv.items.map((li) => (
                      <tr key={li.id}>
                        <td className="text-ink-faint">{li.line_no}</td>
                        <td>{li.description ?? "—"}</td>
                        <td className="text-ink-soft">{li.hsn_sac ?? "—"}</td>
                        <td className="num">{li.quantity ? Number(li.quantity) : "—"}</td>
                        <td className="num">{formatMoney(li.unit_price)}</td>
                        <td className="num">{formatMoney(li.taxable_value)}</td>
                        <td className="num">{li.gst_rate ? `${Number(li.gst_rate)}%` : "—"}</td>
                        <td className="num font-medium">{formatMoney(li.line_total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="What the checks found">
            {inv.findings.length === 0 ? <p className="text-sm text-ink-soft">No findings. This invoice passed every automated check.</p> : (
              <ul className="space-y-2.5">
                {[...inv.findings].sort((a, b) => rank(a.severity) - rank(b.severity)).map((f) => (
                  <li key={f.id} className="flex items-start gap-3 text-sm neu-inset px-4 py-3">
                    <span className="mt-1.5"><SeverityDot severity={f.severity} /></span>
                    <div className="min-w-0">
                      <span className="text-xs text-ink-faint mr-2">{f.code}</span>{f.message}
                    </div>
                  </li>
                ))}
              </ul>
            )}
            {inv.llm_explanation && (
              <div className="mt-5 flex gap-3 p-4 rounded-xl bg-accent/10 text-sm">
                <Sparkles className="w-4 h-4 text-accent-soft shrink-0 mt-0.5" aria-hidden />
                <div><div className="font-semibold mb-1">AI summary</div><p className="text-ink-soft">{inv.llm_explanation}</p></div>
              </div>
            )}
          </Card>

          {inv.reconciliation.some((r) => r.status !== "NO_PO") && (
            <Card title="Purchase order match">
              <div className="overflow-x-auto -mx-3">
                <table className="tbl">
                  <thead><tr><th>Invoice line</th><th>PO line</th><th>Outcome</th><th className="num">Qty (inv / PO)</th><th className="num">Price (inv / PO)</th></tr></thead>
                  <tbody>
                    {inv.reconciliation.map((r) => (
                      <tr key={r.id}>
                        <td>{r.invoice_line_no ?? "—"}</td><td>{r.po_line_no ?? "—"}</td>
                        <td>{r.status.replaceAll("_", " ").toLowerCase()}</td>
                        <td className="num">{r.qty_invoiced ? Number(r.qty_invoiced) : "—"} / {r.qty_po ? Number(r.qty_po) : "—"}</td>
                        <td className="num">{formatMoney(r.price_invoiced)} / {formatMoney(r.price_po)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>

        <div className="space-y-6">
          {inv.status === "NEEDS_REVIEW" ? (
            <Card title="Record a decision"><ReviewActions invoiceId={inv.id} /></Card>
          ) : inv.reviewed_by ? (
            <Card title="Decision">
              <p className="text-sm text-ink-soft">
                {inv.status === "REJECTED" ? "Rejected" : "Approved"} by <b className="text-ink">{inv.reviewed_by}</b>
                {inv.reviewed_at ? ` on ${formatDate(inv.reviewed_at)}` : ""}.
              </p>
              {inv.review_notes && <p className="text-sm mt-2">“{inv.review_notes}”</p>}
            </Card>
          ) : null}

          <Card title="Vendor payment">
            <p className="text-sm text-ink-soft mb-4">Credit must be reversed if the vendor isn&apos;t paid within 180 days.</p>
            <PaymentForm invoiceId={inv.id} paidOn={inv.payment_date} />
          </Card>

          <Card title="E-invoice QR" action={<EinvBadge value={inv.einvoice_status} />}>
            {inv.einvoice_data?.comparisons?.length ? (
              <ul className="space-y-2">
                {inv.einvoice_data.comparisons.map((c) => (
                  <li key={c.field} className="flex items-start gap-2.5 text-sm">
                    {c.match === true ? <CheckCircle2 className="w-4 h-4 text-good mt-0.5 shrink-0" aria-label="matches" />
                      : c.match === false ? <CircleAlert className="w-4 h-4 text-bad mt-0.5 shrink-0" aria-label="differs" />
                      : <CircleHelp className="w-4 h-4 text-ink-faint mt-0.5 shrink-0" aria-label="not compared" />}
                    <div className="min-w-0">
                      <div className="font-medium">{c.field}</div>
                      {c.match === false
                        ? <div className="text-xs"><span className="text-ink-soft">QR says</span> {c.qr} · <span className="text-ink-soft">printed</span> <span className="text-bad">{c.invoice}</span></div>
                        : <div className="text-xs text-ink-soft truncate">{c.qr ?? c.invoice ?? "—"}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-ink-soft">No signed e-invoice QR code was found on this document.</p>}
            {inv.irn && <p className="text-[11px] text-ink-faint mt-4 break-all">IRN {inv.irn}</p>}
          </Card>
        </div>
      </div>
    </div>
  );
}

function rank(s: string) {
  return s === "ERROR" ? 0 : s === "WARNING" ? 1 : 2;
}


function LoadError({ message }: { message: string }) {
  const status = Number(message.slice(0, 3));
  const hint = status === 401 || status === 403
    ? "The site's server was blocked from reading its own API (Vercel Deployment Protection). Set SITE_URL in Vercel to your site address, e.g. https://gst-invoice-assistant.vercel.app, then redeploy."
    : status >= 500
      ? "The API hit an error. Open /api/v1/health/database on this site to check the database."
      : "Please refresh the page. If this keeps happening, check the Vercel logs for this request.";
  return (
    <div className="pt-10 max-w-2xl">
      <Card title="Couldn't load this invoice">
        <p className="text-sm text-ink-soft">{hint}</p>
        <p className="text-xs text-ink-faint mt-3 break-all">Technical detail: {message.replace(/<[^>]+>/g, " ").slice(0, 200)}</p>
        <Link href="/invoices" className="btn mt-5">Back to all invoices</Link>
      </Card>
    </div>
  );
}
