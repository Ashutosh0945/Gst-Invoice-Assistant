import { api } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";
import { Donut } from "@/components/charts";

export const dynamic = "force-dynamic";

const LABELS: Record<string, [string, string]> = {
  MATCHED: ["Matched", "#4ADE80"], PARTIAL: ["Partly delivered (PO line still open)", "#60A5FA"],
  MISMATCH: ["Quantity or price differs", "#F5A524"], NO_PO: ["No PO referenced", "#6F6E8C"], PO_NOT_FOUND: ["PO not found", "#F87171"],
};

export default async function ReconciliationPage() {
  const rows = await api.reconciliationSummary().catch(() => []);
  const total = rows.reduce((s, r) => s + r.line_count, 0);
  return (
    <div>
      <PageHeader title="PO matching" subtitle="Each invoice line checked against its purchase order for vendor, quantity, price and item." />
      <Card>
        {rows.length === 0 ? <Empty title="No purchase order data yet" /> : (
          <div className="grid gap-8 md:grid-cols-[220px_1fr] items-center">
            <Donut center={String(total)} sub="invoice lines" segments={rows.map((r) => ({
              label: LABELS[r.status]?.[0] ?? r.status, value: r.line_count, color: LABELS[r.status]?.[1] ?? "#7C7CF2" }))} />
            <ul className="space-y-3">
              {rows.map((r) => (
                <li key={r.status} className="neu-tile px-4 py-3 flex items-center gap-3">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ background: LABELS[r.status]?.[1] ?? "#7C7CF2" }} />
                  <span className="flex-1">{LABELS[r.status]?.[0] ?? r.status}</span>
                  <span className="tabular font-semibold">{r.line_count}</span>
                  <span className="tabular text-ink-soft w-14 text-right">{total ? `${((r.line_count / total) * 100).toFixed(0)}%` : "—"}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
    </div>
  );
}
