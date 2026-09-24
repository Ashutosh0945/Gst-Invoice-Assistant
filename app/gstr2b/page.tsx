import Link from "next/link";
import { api, formatDate, formatMoney, periodLabel } from "@/lib/api";
import { Card, Empty, FilterChips, PageHeader } from "@/components/ui";
import { Donut } from "@/components/charts";
import { MatchBadge } from "@/components/badges";
import { DeleteImport, Gstr2bUpload } from "@/components/Gstr2bUpload";

export const dynamic = "force-dynamic";

const OUTCOMES: Array<[string, string, string]> = [
  ["MATCHED", "Matched", "#4ADE80"], ["FUZZY_MATCHED", "Number differs", "#60A5FA"],
  ["DATE_MISMATCH", "Date differs", "#7C7CF2"], ["AMOUNT_MISMATCH", "Amount differs", "#F5A524"],
  ["MISSING_IN_BOOKS", "Not in your books", "#F87171"],
];

export default async function Gstr2bPage({ searchParams }: { searchParams: { import?: string; status?: string } }) {
  const [imports, missing] = await Promise.all([api.gstr2bImports().catch(() => []), api.gstr2bMissing().catch(() => [])]);
  const current = imports.find((i) => i.id === searchParams.import) ?? imports[0];
  const records = current ? await api.gstr2bRecords(current.id, searchParams.status).catch(() => []) : [];
  const base = current ? `/gstr2b?import=${current.id}` : "/gstr2b";

  return (
    <div>
      <PageHeader title="GSTR-2B match"
        subtitle="Compare what your vendors reported to the government with the invoices in your books. Credit is only claimable for invoices that appear in GSTR-2B."
        right={<Gstr2bUpload />} />

      {imports.length === 0 ? (
        <Card><Empty title="No GSTR-2B imported yet"
          hint="Download it from the GST portal: Returns Dashboard → select the month → GSTR-2B → Download (JSON). Then use Import GSTR-2B above." /></Card>
      ) : (
        <>
          <div className="flex flex-wrap gap-3 mb-6">
            {imports.map((i) => (
              <Link key={i.id} href={`/gstr2b?import=${i.id}`}
                className={`px-4 py-3 rounded-2xl transition ${i.id === current?.id ? "bg-base shadow-neu-in" : "neu-card hover:-translate-y-0.5"}`}>
                <div className="font-semibold">{periodLabel(i.return_period)}</div>
                <div className="text-xs text-ink-soft">{i.record_count} invoices · {i.missing_in_2b} missing</div>
              </Link>
            ))}
          </div>

          {current && (
            <div className="grid gap-6">
              <Card title={periodLabel(current.return_period)} action={<DeleteImport id={current.id} label={periodLabel(current.return_period)} />}>
                <div className="grid gap-8 md:grid-cols-[200px_1fr_1fr] items-center">
                <div className="flex justify-center">
                  <Donut center={String(current.record_count)} sub="invoices in 2B"
                    segments={OUTCOMES.map(([k, l, c]) => ({ label: l, value: current.status_counts[k] ?? 0, color: c }))} />
                </div>
                <ul className="space-y-2 text-sm">
                  {OUTCOMES.map(([k, l, c]) => (
                    <li key={k} className="flex items-center justify-between">
                      <span className="flex items-center gap-2 text-ink-soft"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}</span>
                      <span className="tabular font-semibold">{current.status_counts[k] ?? 0}</span>
                    </li>
                  ))}
                  <li className="flex items-center justify-between border-t border-base-line pt-2 mt-2">
                    <span className="text-ink-soft">In your books, not in 2B</span>
                    <span className="tabular font-semibold text-bad">{current.missing_in_2b}</span>
                  </li>
                </ul>
                <div className="grid grid-cols-2 gap-3">
                  <div className="neu-inset p-4"><div className="text-xs text-ink-soft">Tax in statement</div><div className="font-bold tabular mt-1">{formatMoney(current.total_tax)}</div></div>
                  <div className="neu-inset p-4"><div className="text-xs text-ink-soft">Matched cleanly</div><div className="font-bold tabular mt-1">{current.record_count ? Math.round(((current.status_counts.MATCHED ?? 0) / current.record_count) * 100) : 0}%</div></div>
                  <div className="col-span-2 text-xs text-ink-faint">From {current.source_filename}{current.generated_on ? ` · generated ${current.generated_on}` : ""}</div>
                </div>
                </div>
              </Card>

              <Card title="Supplier-reported invoices" action={<FilterChips base={base} param="status" current={searchParams.status}
                options={OUTCOMES.map(([k, l]) => ({ value: k, label: l, count: current.status_counts[k] ?? 0 }))} />}>
                {records.length === 0 ? <Empty title="No invoices with this outcome" /> : (
                  <div className="overflow-x-auto -mx-3">
                    <table className="tbl">
                      <thead><tr><th>Supplier</th><th>Invoice</th><th>Date</th><th className="num">Taxable</th><th className="num">Tax</th><th>Outcome</th><th>Detail</th></tr></thead>
                      <tbody>
                        {records.map((r) => (
                          <tr key={r.id}>
                            <td><div className="truncate max-w-[200px]">{r.supplier_name ?? "—"}</div><div className="text-xs text-ink-faint">{r.supplier_gstin}</div></td>
                            <td className="whitespace-nowrap">{r.matched_invoice_id ? <Link className="font-semibold hover:text-accent-soft" href={`/invoices/${r.matched_invoice_id}`}>{r.invoice_number}</Link> : r.invoice_number}</td>
                            <td className="text-ink-soft whitespace-nowrap">{formatDate(r.invoice_date)}</td>
                            <td className="num">{formatMoney(r.taxable_value)}</td>
                            <td className="num">{formatMoney(r.total_tax)}</td>
                            <td><MatchBadge value={r.match_status} /></td>
                            <td className="text-xs text-ink-soft min-w-[240px] max-w-[320px]">
                              {r.match_notes}
                              {!r.itc_available && <div className="text-bad">Portal says ITC not available{r.itc_unavailable_reason ? `: ${r.itc_unavailable_reason}` : ""}</div>}
                              {r.reverse_charge && <div className="text-warn">Reverse charge</div>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>
          )}
        </>
      )}

      <Card className="mt-6" title="In your books but missing from GSTR-2B"
        action={<span className="text-sm text-ink-soft">Ask these vendors to file their GSTR-1</span>}>
        {missing.length === 0 ? <Empty title="Every checked invoice appears in GSTR-2B" /> : (
          <div className="overflow-x-auto -mx-3">
            <table className="tbl">
              <thead><tr><th>Vendor</th><th>Invoice</th><th>Date</th><th className="num">Invoice total</th><th className="num">Credit at risk</th></tr></thead>
              <tbody>
                {missing.map((m) => (
                  <tr key={m.invoice_id}>
                    <td><div>{m.vendor_name ?? "—"}</div><div className="text-xs text-ink-faint">{m.vendor_gstin}</div></td>
                    <td><Link href={`/invoices/${m.invoice_id}`} className="font-semibold hover:text-accent-soft">{m.invoice_number}</Link></td>
                    <td className="text-ink-soft">{formatDate(m.invoice_date)}</td>
                    <td className="num">{formatMoney(m.grand_total)}</td>
                    <td className="num font-semibold text-bad">{formatMoney(m.at_risk_itc)}</td>
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
