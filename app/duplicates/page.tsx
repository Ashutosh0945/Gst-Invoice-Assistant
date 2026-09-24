import Link from "next/link";
import { api } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function DuplicatesPage() {
  const rows = await api.duplicates().catch(() => []);
  return (
    <div>
      <PageHeader title="Duplicates" subtitle="Re-uploaded files and likely duplicate bills, caught by matching vendor, invoice number, date window and amount. Duplicates are kept out of your tax credit until reviewed." />
      <Card>
        {rows.length === 0 ? <Empty title="No duplicates detected" /> : (
          <div className="overflow-x-auto -mx-3">
            <table className="tbl">
              <thead><tr><th>Invoice</th><th>File</th><th>What matched</th><th /></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td className="font-semibold">{r.invoice_number ?? "—"}</td>
                    <td className="text-xs text-ink-soft">{r.source_filename}</td>
                    <td className="text-ink-soft">{r.message}</td>
                    <td className="text-right"><Link href={`/invoices/${r.invoice_id}`} className="btn py-1.5">Open</Link></td>
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
