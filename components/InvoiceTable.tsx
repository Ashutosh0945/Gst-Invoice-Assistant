import Link from "next/link";
import type { InvoiceSummary } from "@/lib/api";
import { formatDate, formatMoney, formatPercent } from "@/lib/api";
import { EinvBadge, StatusBadge, TwoBBadge } from "@/components/badges";

export function InvoiceTable({ rows, action, showAiPreview }: { rows: InvoiceSummary[]; action?: string; showAiPreview?: boolean }) {
  return (
    <div className="overflow-x-auto -mx-3">
      <table className="tbl">
        <thead>
          <tr>
            <th>Invoice</th><th>Vendor</th><th>Date</th><th className="num">Total</th>
            <th className="num">Confidence</th><th>GSTR-2B</th><th>E-invoice</th><th>Status</th>{action && <th />}
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => (
            <tr key={i.id}>
              <td>
                <Link href={`/invoices/${i.id}`} className="font-semibold hover:text-accent-soft">
                  {i.invoice_number ?? i.source_filename}
                </Link>
                {showAiPreview && i.llm_explanation && (
                  <div className="flex items-start gap-1 mt-1 max-w-[280px]">
                    <span className="text-accent-soft shrink-0" title="AI summary">✦</span>
                    <p className="text-xs text-ink-faint line-clamp-2">{i.llm_explanation}</p>
                  </div>
                )}
              </td>
              <td>
                <div className="text-ink truncate max-w-[220px]">{i.vendor_name_raw ?? "—"}</div>
                <div className="text-xs text-ink-faint">{i.vendor_gstin_raw ?? ""}</div>
              </td>
              <td className="text-ink-soft whitespace-nowrap">{formatDate(i.invoice_date)}</td>
              <td className="num font-medium">{formatMoney(i.grand_total)}</td>
              <td className="num text-ink-soft">{formatPercent(i.confidence_score)}</td>
              <td><TwoBBadge value={i.gstr2b_status} /></td>
              <td><EinvBadge value={i.einvoice_status} /></td>
              <td><StatusBadge value={i.status} /></td>
              {action && (
                <td className="text-right">
                  <Link href={`/invoices/${i.id}`} className="btn py-1.5">{action}</Link>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
