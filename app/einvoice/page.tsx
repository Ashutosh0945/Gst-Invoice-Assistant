import Link from "next/link";
import { CheckCircle2, Fingerprint, FileWarning, QrCode } from "lucide-react";
import { api, formatMoney } from "@/lib/api";
import { Card, Empty, PageHeader, StatTile } from "@/components/ui";
import { EinvBadge } from "@/components/badges";
import { QrVerifier } from "@/components/QrVerifier";

export const dynamic = "force-dynamic";

export default async function EinvoicePage() {
  const s = await api.einvoiceSummary().catch(() => null);
  const c = s?.counts ?? {};

  return (
    <div>
      <PageHeader title="E-invoice checks"
        subtitle="An e-invoice carries a QR code signed by the government portal. We read it, check the signature, and compare it with what is printed — so an edited total or a copied QR is caught." />
      <div className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile icon={CheckCircle2} tone="good" value={String(c.VERIFIED ?? 0)} title="Verified" sub="signature valid, fields match" />
        <StatTile icon={FileWarning} tone="bad" value={String(c.MISMATCH ?? 0)} title="Printout differs" sub="QR and invoice disagree" />
        <StatTile icon={Fingerprint} tone="bad" value={String(c.SIGNATURE_INVALID ?? 0)} title="Forged signature" sub="not signed by the portal" />
        <StatTile icon={QrCode} tone="muted" value={String(c.NO_QR ?? 0)} title="No QR code" sub="not an e-invoice" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_420px] mt-6">
        <div className="space-y-6 min-w-0">
          <Card title="Needs attention">
            {!s || s.flagged.length === 0 ? <Empty title="No QR problems found" /> : (
              <ul className="space-y-3">
                {s.flagged.map((r) => (
                  <li key={r.invoice_id}>
                    <Link href={`/invoices/${r.invoice_id}`} className="block neu-tile p-4 hover:text-white">
                      <div className="flex flex-wrap items-center gap-3">
                        <span className="font-semibold">{r.invoice_number}</span>
                        <span className="text-sm text-ink-soft">{r.vendor_name}</span>
                        <span className="flex-1" />
                        <EinvBadge value={r.einvoice_status} />
                      </div>
                      {r.comparisons.filter((x) => x.match === false).map((x) => (
                        <p key={x.field} className="text-sm mt-2">
                          {x.field}: QR says <b>{x.qr}</b>, printed <b className="text-bad">{x.invoice}</b>
                        </p>
                      ))}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="E-invoices received">
            {!s || s.recent.length === 0 ? <Empty title="No e-invoices yet" /> : (
              <div className="overflow-x-auto -mx-3">
                <table className="tbl">
                  <thead><tr><th>Invoice</th><th>Vendor</th><th className="num">Total</th><th>IRN</th><th>Result</th></tr></thead>
                  <tbody>
                    {s.recent.map((r) => (
                      <tr key={r.invoice_id}>
                        <td><Link href={`/invoices/${r.invoice_id}`} className="font-semibold hover:text-accent-soft">{r.invoice_number}</Link></td>
                        <td className="text-ink-soft whitespace-nowrap">{r.vendor_name}</td>
                        <td className="num">{formatMoney(r.grand_total)}</td>
                        <td className="text-xs text-ink-faint">{r.irn?.slice(0, 14)}…</td>
                        <td><EinvBadge value={r.einvoice_status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
        <Card title="Check a QR code" className="self-start"><QrVerifier /></Card>
      </div>
    </div>
  );
}
