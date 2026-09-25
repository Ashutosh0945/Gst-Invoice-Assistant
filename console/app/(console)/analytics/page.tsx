import { api, formatCompact } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";
import { BarList, C, Donut, StackedBars } from "@/components/charts";
import { SeverityDot } from "@/components/badges";

export const dynamic = "force-dynamic";

const RATE_COLORS = ["#4ADE80", "#60A5FA", "#7C7CF2", "#F5A524", "#F87171"];

export default async function AnalyticsPage() {
  const [gstByRate, hsn, findings, daily, vendors] = await Promise.all([
    api.gstByRate().catch(() => []), api.hsnSummary().catch(() => []), api.findingFrequency().catch(() => []),
    api.dailyIntake().catch(() => []), api.vendorSpend().catch(() => []),
  ]);
  const totalGst = gstByRate.reduce((s, r) => s + Number(r.total_gst ?? 0), 0);
  const intake = daily.slice(-14).map((d) => ({
    label: new Date(`${d.day.slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
    auto: d.auto_approved, review: d.needs_review, rejected: d.rejected,
  }));

  return (
    <div>
      <PageHeader title="GST analytics" subtitle="Figures from approved and auto-approved invoices only — the numbers a return would actually include." />
      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <Card title="GST by rate slab">
          {gstByRate.length === 0 ? <Empty title="No approved invoices yet" /> : (
            <>
              <div className="flex justify-center">
                <Donut center={formatCompact(totalGst)} sub="total GST" segments={gstByRate.map((r, i) => ({
                  label: `${Number(r.gst_rate ?? 0)}%`, value: Number(r.total_gst ?? 0), color: RATE_COLORS[i % RATE_COLORS.length] }))} />
              </div>
              <ul className="mt-5 space-y-2 text-sm">
                {gstByRate.map((r, i) => (
                  <li key={i} className="flex justify-between">
                    <span className="flex items-center gap-2 text-ink-soft"><span className="w-2.5 h-2.5 rounded-full" style={{ background: RATE_COLORS[i % RATE_COLORS.length] }} />{Number(r.gst_rate ?? 0)}% slab · {r.invoice_count} invoices</span>
                    <span className="tabular font-semibold">{formatCompact(r.total_gst)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
        <Card title="Invoices processed per day">
          {intake.length === 0 ? <Empty title="No invoices in the last 30 days" /> : (
            <StackedBars data={intake} format={(n) => String(Math.round(n))} series={[
              { key: "auto", label: "Auto-approved", color: C.eligible }, { key: "review", label: "Needs review", color: C.review },
              { key: "rejected", label: "Rejected", color: C.atRisk }]} />
          )}
        </Card>
      </div>
      <div className="grid gap-6 xl:grid-cols-2 mt-6">
        <Card title="Top HSN / SAC codes by taxable value">
          {hsn.length === 0 ? <Empty title="No data yet" /> : (
            <BarList format={formatCompact} rows={hsn.slice(0, 8).map((h) => ({
              label: h.hsn_sac ?? "—", value: Number(h.total_taxable_value ?? 0), hint: `${h.line_count} lines` }))} />
          )}
        </Card>
        <Card title="Top vendors by spend">
          {vendors.length === 0 ? <Empty title="No data yet" /> : (
            <BarList format={formatCompact} color={C.info} rows={vendors.slice(0, 8).map((v) => ({
              label: v.vendor_name ?? v.gstin ?? "—", value: Number(v.total_spend ?? 0), hint: `${v.invoice_count} inv.` }))} />
          )}
        </Card>
      </div>
      <Card className="mt-6" title="Most frequent findings">
        {findings.length === 0 ? <Empty title="No findings recorded yet" /> : (
          <div className="grid gap-3 md:grid-cols-2">
            {findings.slice(0, 12).map((f, i) => (
              <div key={i} className="neu-tile px-4 py-3 flex items-center gap-3 text-sm">
                <SeverityDot severity={f.severity} />
                <span className="font-semibold">{f.code.replaceAll("_", " ").toLowerCase()}</span>
                <span className="text-ink-faint">{f.category}</span>
                <span className="flex-1" />
                <span className="tabular text-ink-soft">{f.occurrence_count}× · {f.invoice_count} inv.</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
