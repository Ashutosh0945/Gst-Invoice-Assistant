import Link from "next/link";
import { api, formatCompact, formatMoney } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";
import { Meter } from "@/components/charts";
import { RiskBadge } from "@/components/badges";

export const dynamic = "force-dynamic";

const COLOR = { Low: "#4ADE80", Medium: "#F5A524", High: "#F87171" } as const;

export default async function VendorsPage() {
  const vendors = await api.vendorRisk().catch(() => []);
  const count = (l: string) => vendors.filter((v) => v.risk_level === l).length;

  return (
    <div>
      <PageHeader title="Vendor risk"
        subtitle="Each vendor is scored 0–100 (40+ is high risk) on how reliably they report your invoices to the government, plus mismatches, QR problems and validation errors." />
      <div className="grid gap-6 sm:grid-cols-3 mb-6">
        {(["High", "Medium", "Low"] as const).map((l) => (
          <div key={l} className="neu-card p-5 flex items-center gap-4">
            <span className="w-3 h-12 rounded-full" style={{ background: COLOR[l] }} />
            <div><div className="text-2xl font-extrabold tabular">{count(l)}</div><div className="text-sm text-ink-soft">{l} risk vendors</div></div>
          </div>
        ))}
      </div>
      <Card title="All vendors">
        {vendors.length === 0 ? <Empty title="No vendors yet" /> : (
          <div className="overflow-x-auto -mx-3">
            <table className="tbl">
              <thead><tr><th>Vendor</th><th>Risk</th><th className="num">Score</th><th>2B filing rate</th><th className="num">Invoices</th><th className="num">Spend</th><th className="num">Credit at risk</th><th>Why</th></tr></thead>
              <tbody>
                {vendors.map((v) => (
                  <tr key={v.vendor_gstin}>
                    <td><Link href={`/invoices?q=${v.vendor_gstin}`} className="font-semibold hover:text-accent-soft">{v.vendor_name ?? "—"}</Link>
                      <div className="text-xs text-ink-faint">{v.vendor_gstin}</div></td>
                    <td><RiskBadge value={v.risk_level} /></td>
                    <td className="num"><div className="flex items-center justify-end gap-2"><Meter value={v.risk_score / 100} color={COLOR[v.risk_level]} /><span className="w-8">{Math.round(v.risk_score)}</span></div></td>
                    <td className="tabular">{v.filing_rate === null ? <span className="text-ink-faint">not checked</span> : `${Math.round(v.filing_rate * 100)}%`}</td>
                    <td className="num">{v.invoice_count}</td>
                    <td className="num">{formatCompact(v.total_spend)}</td>
                    <td className={`num ${Number(v.at_risk_itc) ? "text-bad font-semibold" : "text-ink-faint"}`}>{formatMoney(v.at_risk_itc)}</td>
                    <td className="text-xs text-ink-soft max-w-[280px]">{v.reasons.length ? v.reasons.join(" · ") : "No issues found"}</td>
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
