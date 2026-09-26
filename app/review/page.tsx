import { api } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";
import { InvoiceTable } from "@/components/InvoiceTable";

export const dynamic = "force-dynamic";

export default async function ReviewQueuePage() {
  const invoices = await api.listInvoices({ status: "NEEDS_REVIEW", limit: 200 }).catch(() => []);
  return (
    <div>
      <PageHeader title="Review queue"
        subtitle="Invoices the rule engine couldn't approve on its own: it found an error, or it wasn't confident it read the invoice correctly." />
      <Card title={`${invoices.length} waiting`}>
        {invoices.length === 0
          ? <Empty title="Nothing waiting on review" hint="New invoices that need a human decision will appear here." />
          : <InvoiceTable rows={invoices} action="Review" showAiPreview />}
      </Card>
    </div>
  );
}
