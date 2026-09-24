import Link from "next/link";
import { Ban, BadgeIndianRupee, CircleHelp, ShieldAlert } from "lucide-react";
import { api, formatCompact, formatDate, formatMoney } from "@/lib/api";
import { Card, Empty, FilterChips, Kpi, PageHeader } from "@/components/ui";
import { Donut } from "@/components/charts";
import { ItcBadge } from "@/components/badges";

export const dynamic = "force-dynamic";

const STATUS: Array<[string, string, string]> = [
  ["ELIGIBLE", "Eligible", "#4ADE80"], ["AWAITING_2B", "Awaiting 2B", "#7C7CF2"], ["PARTIALLY_ELIGIBLE", "Partly eligible", "#60A5FA"],
  ["NEEDS_REVIEW", "Needs review", "#F5A524"], ["NOT_IN_2B", "Not in 2B", "#F87171"], ["REVERSAL_DUE", "Reversal due", "#FB7185"],
  ["BLOCKED", "Blocked", "#6F6E8C"], ["LAPSED", "Lapsed", "#B91C1C"], ["NOT_APPLICABLE", "Not applicable", "#3F3E5C"],
];

export default async function ItcPage({ searchParams }: { searchParams: { status?: string } }) {
  const [sum, rows] = await Promise.all([api.itcSummary().catch(() => null), api.itcAssessments(searchParams.status).catch(() => [])]);
  const counts = Object.fromEntries((sum?.by_status ?? []).map((s) => [s.status, s.invoice_count]));
  const totalCount = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div>
      <PageHeader title="Input tax credit"
        subtitle="How much GST you can claim back, and exactly why any of it is held back. Every decision comes from written rules in the CGST Act, never from the AI." />
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={BadgeIndianRupee} tone="good" label="Claimable" value={formatCompact(sum?.eligible_itc)} href="/itc?status=ELIGIBLE" />
        <Kpi icon={CircleHelp} tone="warn" label="Needs a decision" value={formatCompact(sum?.review_itc)} href="/itc?status=NEEDS_REVIEW" />
        <Kpi icon={ShieldAlert} tone="bad" label="At risk" value={formatCompact(sum?.at_risk_itc)} href="/itc?status=NOT_IN_2B" />
        <Kpi icon={Ban} tone="muted" label="Blocked by law" value={formatCompact(sum?.blocked_itc)} href="/itc?status=BLOCKED" />
      </div>

      <div className="grid gap-6 mt-6">
        <Card title="Invoices by status">
          <div className="grid gap-8 md:grid-cols-[200px_1fr] items-center">
          <div className="flex justify-center">
            <Donut center={String(totalCount)} sub="invoices assessed"
              segments={STATUS.map(([k, l, c]) => ({ label: l, value: counts[k] ?? 0, color: c }))} />
          </div>
          <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-2 text-sm">
            {STATUS.filter(([k]) => counts[k]).map(([k, l, c]) => (
              <li key={k} className="flex justify-between neu-tile px-3.5 py-2.5">
                <span className="flex items-center gap-2 text-ink-soft"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}</span>
                <span className="tabular font-semibold">{counts[k]}</span>
              </li>
            ))}
          </ul>
          </div>
        </Card>

        <Card title="Invoice by invoice" action={<FilterChips base="/itc" param="status" current={searchParams.status}
          options={STATUS.filter(([k]) => counts[k]).map(([k, l]) => ({ value: k, label: l, count: counts[k] }))} />}>
          {rows.length === 0 ? <Empty title="No invoices in this status" /> : (
            <div className="overflow-x-auto -mx-3">
              <table className="tbl">
                <thead><tr><th>Invoice</th><th>Status</th><th className="num">GST</th><th className="num">Claimable</th><th className="num">At risk / blocked</th><th>Main reason</th></tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const main = (r.reasons ?? []).find((x) => x.severity === "ERROR") ?? (r.reasons ?? []).find((x) => x.severity === "WARNING");
                    const held = Number(r.at_risk_itc) + Number(r.blocked_itc) + Number(r.review_itc);
                    return (
                      <tr key={r.invoice_id}>
                        <td>
                          <Link href={`/invoices/${r.invoice_id}`} className="font-semibold hover:text-accent-soft">{r.invoice_number}</Link>
                          <div className="text-xs text-ink-faint">{r.vendor_name} · {formatDate(r.invoice_date)}</div>
                        </td>
                        <td><ItcBadge value={r.status} /></td>
                        <td className="num">{formatMoney(r.total_itc)}</td>
                        <td className="num text-good">{formatMoney(r.eligible_itc)}</td>
                        <td className={`num ${held ? "text-bad" : "text-ink-faint"}`}>{formatMoney(String(held))}</td>
                        <td className="text-xs text-ink-soft min-w-[300px] max-w-[440px]">{main?.message ?? "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
