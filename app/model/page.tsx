import { api, formatDate } from "@/lib/api";
import { Card, Empty, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const COLORS = ["#6F6E8C", "#60A5FA", "#4ADE80", "#7C7CF2"];

export default async function ModelPage() {
  const b = await api.benchmark().catch(() => null);
  return (
    <div>
      <PageHeader title="Model accuracy"
        subtitle="How accurately each extractor reads invoices it has never seen, measured field by field against exact ground truth." />
      {!b ? (
        <Card><Empty title="No benchmark has been run yet" hint="Run: python -m ml.benchmark — and after training, python -m ml.benchmark --model models/layoutlmv3-gst" /></Card>
      ) : (
        <>
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            {Object.entries(b.extractors).map(([name, r], i) => (
              <div key={name} className="neu-card p-6">
                <div className="text-sm text-ink-soft">{name}</div>
                <div className="text-[34px] font-extrabold tabular mt-2" style={{ color: COLORS[i % COLORS.length] }}>{pct(r.overall_field_accuracy)}</div>
                <div className="label mt-1">FIELD ACCURACY</div>
              </div>
            ))}
            {!b.extractors["LayoutLMv3"] && (
              <div className="neu-card p-6 border border-dashed border-base-line">
                <div className="text-sm text-ink-soft">LayoutLMv3</div>
                <div className="text-lg font-bold mt-3">Not trained yet</div>
                <p className="text-xs text-ink-soft mt-2">Train with ml/train_layoutlm_colab.ipynb, then re-run the benchmark.</p>
              </div>
            )}
          </div>

          <Card className="mt-6" title="Accuracy by invoice layout">
            <div className="space-y-6">
              {b.layouts.map((layout) => (
                <div key={layout}>
                  <div className="font-semibold mb-3">Layout {layout}</div>
                  <div className="space-y-2.5">
                    {Object.entries(b.extractors).map(([name, r], i) => {
                      const v = r.layouts[layout]?.field_accuracy ?? 0;
                      return (
                        <div key={name} className="grid grid-cols-[150px_1fr_64px] items-center gap-3 text-sm">
                          <span className="text-ink-soft truncate">{name}</span>
                          <div className="h-3 rounded-full bg-base-deep shadow-neu-in overflow-hidden">
                            <div className="h-full rounded-full" style={{ width: `${v * 100}%`, background: COLORS[i % COLORS.length] }} />
                          </div>
                          <span className="tabular text-right font-semibold">{pct(v)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card className="mt-6" title="Detail">
            <div className="overflow-x-auto -mx-3">
              <table className="tbl">
                <thead><tr><th>Extractor</th><th>Layout</th><th className="num">Header fields</th><th className="num">Line items</th><th className="num">Item count right</th><th className="num">Perfect invoices</th><th className="num">ms / invoice</th></tr></thead>
                <tbody>
                  {Object.entries(b.extractors).flatMap(([name, r]) => Object.entries(r.layouts).map(([layout, v]) => (
                    <tr key={name + layout}>
                      <td className="font-semibold">{name}</td><td className="text-ink-soft">{layout}</td>
                      <td className="num">{pct(v.header_accuracy)}</td><td className="num">{pct(v.line_item_accuracy)}</td>
                      <td className="num">{pct(v.item_count_accuracy)}</td><td className="num">{pct(v.perfect_documents)}</td>
                      <td className="num text-ink-soft">{v.ms_per_document}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-ink-faint mt-4">
              {b.documents_per_layout} held-out synthetic invoices per layout · run {formatDate(b.generated_at)}.
              Each rule-based reader is near-perfect on the layout it was written for and weak on the other; a trained model is meant to generalise without new rules.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
