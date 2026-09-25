import Link from "next/link";
import { api } from "@/lib/api";
import { Card, Empty, FilterChips, PageHeader } from "@/components/ui";
import { InvoiceTable } from "@/components/InvoiceTable";

export const dynamic = "force-dynamic";

const STATUSES = [
  { value: "NEEDS_REVIEW", label: "Needs review" }, { value: "AUTO_APPROVED", label: "Auto-approved" },
  { value: "APPROVED", label: "Approved" }, { value: "REJECTED", label: "Rejected" },
];

export default async function InvoicesPage({ searchParams }: { searchParams: { q?: string; status?: string } }) {
  const all = await api.listInvoices({ status: searchParams.status, limit: 500 }).catch(() => []);
  const q = (searchParams.q || "").trim().toLowerCase();
  const rows = q
    ? all.filter((i) => [i.invoice_number, i.vendor_name_raw, i.vendor_gstin_raw, i.source_filename]
        .some((v) => v?.toLowerCase().includes(q)))
    : all;
  const base = q ? `/invoices?q=${encodeURIComponent(q)}` : "/invoices";

  return (
    <div>
      <PageHeader title="All invoices" subtitle={q ? `Showing matches for “${searchParams.q}”` : "Every invoice that has been read, checked and scored."}
        right={<Link href="/upload" className="btn-primary">Upload invoice</Link>} />
      <Card title={`${rows.length} invoice${rows.length === 1 ? "" : "s"}`}
        action={<FilterChips base={base} param="status" current={searchParams.status} options={STATUSES} />}>
        {rows.length === 0
          ? <Empty title={q ? "No invoices match that search" : "No invoices yet"}
              hint={q ? "Try an invoice number, part of a vendor name, or a GSTIN." : "Upload a PDF or image to get started."} />
          : <InvoiceTable rows={rows} />}
      </Card>
    </div>
  );
}
