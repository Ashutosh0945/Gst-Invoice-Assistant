import Link from "next/link";
import { AlertTriangle, BadgeIndianRupee, FileStack, ListChecks, QrCode, ShieldAlert, Store } from "lucide-react";
import { api, formatCompact, formatDate, formatMoney, periodLabel } from "@/lib/api";
import { Card, Empty, Kpi, Legend, PageHeader, StatTile } from "@/components/ui";
import { C, SegmentBar, StackedBars } from "@/components/charts";
import { ItcBadge, StatusBadge } from "@/components/badges";

export const dynamic = "force-dynamic";

function greeting() {
  const h = Number(new Date().toLocaleString("en-IN", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default async function OverviewPage() {
  const [ov, statuses, recent, missing, vendors, itcRows] = await Promise.all([
    api.overview().catch(() => null),
    api.statusSummary().catch(() => []),
    api.listInvoices({ limit: 6 }).catch(() => []),
    api.gstr2bMissing().catch(() => []),
    api.vendorRisk().catch(() => []),
    api.itcAssessments().catch(() => []),
  ]);
  const totalInvoices = statuses.reduce((s, r) => s + r.invoice_count, 0);
  const needsReview = statuses.find((s) => s.status === "NEEDS_REVIEW")?.invoice_count ?? 0;
  const itc = ov?.itc;
  const einvBad = ["MISMATCH", "SIGNATURE_INVALID", "MALFORMED"].reduce((s, k) => s + (ov?.einvoice_counts[k] ?? 0), 0);
  const highRisk = vendors.filter((v) => v.risk_level === "High").length;
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" });
  const months = (ov?.itc_by_month ?? []).map((m) => ({
    label: new Date(`${m.month}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short" }),
    eligible: Number(m.eligible), review: Number(m.review), at_risk: Number(m.at_risk), blocked: Number(m.blocked),
  }));
  const urgent = itcRows.filter((r) => Number(r.at_risk_itc) > 0).slice(0, 5);

  return (
    <div>
      <PageHeader
        title={`${greeting()} 👋`}
        subtitle="Here's where your GST input credit stands today"
        right={<div className="sm:text-right"><div className="font-semibold">{today}</div><div className="text-sm text-ink-soft">Live data</div></div>}
      />

      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={ShieldAlert} tone="bad" label="Credit at risk" value={formatCompact(itc?.credit_at_risk)}
          pill={`${missing.length} not in 2B`} href="/itc?status=NOT_IN_2B" />
        <Kpi icon={BadgeIndianRupee} tone="good" label="Claimable ITC" value={formatCompact(itc?.eligible_itc)}
          pill={`of ${formatCompact(itc?.total_itc)}`} href="/itc" />
        <Kpi icon={ListChecks} tone="warn" label="Awaiting review" value={String(needsReview)}
          pill="open queue" href="/review" />
        <Kpi icon={FileStack} tone="accent" label="Invoices processed" value={String(totalInvoices)}
          pill={ov?.latest_gstr2b ? `2B: ${periodLabel(ov.latest_gstr2b.return_period)}` : "no 2B yet"} href="/invoices" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_380px] mt-6">
        <Card title="Input tax credit by month" action={<Legend items={[
          { label: "Claimable", color: C.eligible }, { label: "Review", color: C.review },
          { label: "At risk", color: C.atRisk }, { label: "Blocked", color: C.blocked }]} />}>
          {months.length ? (
            <StackedBars data={months} format={(n) => formatCompact(n)} series={[
              { key: "eligible", label: "Claimable", color: C.eligible }, { key: "review", label: "Review", color: C.review },
              { key: "at_risk", label: "At risk", color: C.atRisk }, { key: "blocked", label: "Blocked", color: C.blocked }]} />
          ) : <Empty title="No invoices yet" hint="Upload an invoice or run scripts/seed_demo_data.py to see your credit by month." />}
        </Card>
        <div className="grid gap-6 content-start">
          <StatTile icon={AlertTriangle} tone="bad" value={String(missing.length)} title="Missing in GSTR-2B"
            sub="vendor hasn't filed yet" href="/gstr2b" />
          <StatTile icon={QrCode} tone={einvBad ? "bad" : "good"} value={String(einvBad)} title="E-invoice problems"
            sub="QR doesn't match the printout" href="/einvoice" />
          <StatTile icon={Store} tone="warn" value={String(highRisk)} title="High-risk vendors"
            sub={`of ${vendors.length} vendors scored`} href="/vendors" />
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2 mt-6">
        <Card title="Where your credit stands">
          {itc && Number(itc.total_itc) > 0 ? (
            <>
              <SegmentBar segments={[
                { label: "Claimable", value: Number(itc.eligible_itc), color: C.eligible },
                { label: "Review", value: Number(itc.review_itc), color: C.review },
                { label: "At risk", value: Number(itc.at_risk_itc), color: C.atRisk },
                { label: "Blocked", value: Number(itc.blocked_itc), color: C.blocked }]} />
              <dl className="grid grid-cols-2 gap-4 mt-6">
                {[["Claimable now", itc.eligible_itc, C.eligible], ["Needs a decision", itc.review_itc, C.review],
                  ["At risk", itc.at_risk_itc, C.atRisk], ["Blocked by law", itc.blocked_itc, C.blocked]].map(([l, v, c]) => (
                  <div key={l} className="neu-tile p-4">
                    <dt className="text-sm text-ink-soft flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}
                    </dt>
                    <dd className="text-xl font-bold tabular mt-1">{formatMoney(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : <Empty title="No credit to show yet" />}
        </Card>

        <Card title="Act on these first" action={<Link href="/itc" className="text-sm text-accent-soft">All ITC</Link>}>
          {urgent.length === 0 ? <Empty title="Nothing at risk" hint="Every invoice's credit is either claimable or already decided." /> : (
            <ul className="space-y-3">
              {urgent.map((r) => (
                <li key={r.invoice_id}>
                  <Link href={`/invoices/${r.invoice_id}`} className="flex items-center gap-3 neu-tile p-3.5 hover:text-white">
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold truncate">{r.vendor_name ?? "Unknown vendor"}</div>
                      <div className="text-xs text-ink-soft">{r.invoice_number} · {formatDate(r.invoice_date)}</div>
                    </div>
                    <ItcBadge value={r.status} />
                    <div className="text-right tabular font-semibold text-bad w-28">{formatMoney(r.at_risk_itc)}</div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-6" title="Recent invoices" action={<Link href="/invoices" className="text-sm text-accent-soft">View all</Link>}>
        {recent.length === 0 ? <Empty title="No invoices yet" action={<Link href="/upload" className="btn-primary">Upload an invoice</Link>} /> : (
          <div className="overflow-x-auto -mx-3">
            <table className="tbl">
              <thead><tr><th>Invoice</th><th>Vendor</th><th>Date</th><th className="num">Total</th><th>Status</th></tr></thead>
              <tbody>
                {recent.map((i) => (
                  <tr key={i.id}>
                    <td><Link href={`/invoices/${i.id}`} className="font-semibold hover:text-accent-soft">{i.invoice_number ?? i.source_filename}</Link></td>
                    <td className="text-ink-soft">{i.vendor_name_raw ?? "—"}</td>
                    <td className="text-ink-soft whitespace-nowrap">{formatDate(i.invoice_date)}</td>
                    <td className="num">{formatMoney(i.grand_total)}</td>
                    <td><StatusBadge value={i.status} /></td>
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
