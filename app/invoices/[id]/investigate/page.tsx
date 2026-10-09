"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, CircleAlert, CircleMinus, Loader2, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import { ai, inr, type Investigation } from "@/lib/ai";
import { InvestigationWorkspace } from "@/components/InvestigationWorkspace";

const ICON = { pass: [CheckCircle2, "text-good", "Passed"], warn: [TriangleAlert, "text-warn", "Check"], fail: [CircleAlert, "text-bad", "Problem"], na: [CircleMinus, "text-ink-faint", "Not applicable"] } as const;

function Inner() {
  const { id } = useParams<{ id: string }>();
  const wantExplain = useSearchParams().get("explain") === "1";
  const [data, setData] = useState<Investigation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [explaining, setExplaining] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const explain = async () => {
    setExplaining(true);
    try { setData(await ai.investigate(id, true)); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setExplaining(false); }
  };
  useEffect(() => {
    ai.investigate(id).then((d) => { setData(d); if (wantExplain) explain(); }).catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (error) return <div className="pt-10"><div className="neu-card p-8 text-center"><p className="font-semibold">Couldn&apos;t investigate this invoice</p><p className="text-sm text-ink-soft mt-1">{error}</p></div></div>;
  if (!data) return <div className="pt-8 space-y-3 animate-pulse">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="h-16 neu-card" />)}</div>;
  const inv = data.invoice;

  return (
    <div className="max-w-6xl">
      <Link href={`/invoices/${inv.id}`} className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink-strong mt-6"><ArrowLeft className="w-4 h-4" aria-hidden />Back to invoice</Link>
      <header className="pt-4 pb-6">
        <h1 className="text-[28px] font-extrabold tracking-tight">Investigation · {inv.invoice_number || "Invoice"}</h1>
        <p className="text-ink-soft">{inv.vendor || "Unknown vendor"} · {inv.invoice_date || "no date"} · {inr(inv.grand_total)} (GST {inr(inv.gst)})</p>
      </header>

      <section className="neu-card p-5 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 font-semibold"><Sparkles className="w-4 h-4 text-accent-soft" aria-hidden />AI explanation</div>
          <button className="btn py-1.5" onClick={explain} disabled={explaining}>
            {explaining ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Explaining…</> : data.explanation ? "Regenerate" : "Explain this invoice"}
          </button>
        </div>
        {data.explanation ? (
          <>
            <p className="mt-3 whitespace-pre-wrap leading-relaxed">{data.explanation.text}</p>
            <p className="text-[11px] text-ink-faint mt-2 inline-flex items-center gap-1"><ShieldCheck className="w-3 h-3 text-good" aria-hidden />
              {data.explanation.source === "ai" ? "AI wording, fact-checked against the results below. The AI cannot change any result." : "Rule-based summary of the results below."}
              {data.explanation.note ? ` ${data.explanation.note}` : ""}</p>
          </>
        ) : <p className="text-sm text-ink-soft mt-2">The results below come from the rule engine. Ask the AI to explain them in plain English.</p>}
      </section>

      <div className="flex flex-wrap gap-2 mb-6">
        <Link href={`/invoices/${inv.id}/message`} className="btn">Draft message to vendor</Link>
        {data.stages.some((s) => s.stage === "Purchase order" && (s.status === "fail" || s.status === "warn")) && <PoExplain id={inv.id} />}
      </div>

      <InvestigationWorkspace id={inv.id} />

      <h2 className="font-bold text-lg mb-3">All checks, stage by stage</h2>
      <ol className="relative border-l-2 border-base-line ml-3 space-y-4">
        {data.stages.map((s) => {
          const [Icon, cls, label] = ICON[s.status];
          const hasEv = s.evidence.length > 0;
          return (
            <li key={s.stage} className="ml-6">
              <span className={`absolute -left-[13px] w-6 h-6 rounded-full bg-base grid place-items-center ${cls}`}><Icon className="w-5 h-5" aria-hidden /></span>
              <div className="neu-card p-4">
                <div className="flex flex-wrap justify-between gap-2">
                  <div className="font-semibold">{s.stage}</div>
                  <span className={`text-xs font-semibold ${cls}`}>{label}</span>
                </div>
                <p className="text-sm text-ink-soft mt-1">{s.summary}</p>
                {hasEv && (
                  <>
                    <button className="text-xs text-accent-soft mt-2" aria-expanded={open === s.stage} onClick={() => setOpen(open === s.stage ? null : s.stage)}>
                      {open === s.stage ? "Hide evidence" : `Show evidence (${s.evidence.length})`}
                    </button>
                    {open === s.stage && (
                      <div className="mt-2 overflow-x-auto"><table className="tbl text-xs">
                        <thead><tr>{Object.keys(s.evidence[0]).map((k) => <th key={k}>{k.replaceAll("_", " ")}</th>)}</tr></thead>
                        <tbody>{s.evidence.map((e, i) => <tr key={i}>{Object.values(e).map((v, j) => <td key={j}>{v === null || v === undefined ? "—" : String(v)}</td>)}</tr>)}</tbody>
                      </table></div>
                    )}
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function PoExplain({ id }: { id: string }) {
  const [text, setText] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return text ? <p className="w-full neu-inset p-3 text-sm">{text}</p> : (
    <button className="btn" disabled={busy} onClick={async () => { setBusy(true); try { setText((await ai.reconPo(id)).explanation.text); } finally { setBusy(false); } }}>
      {busy ? "Explaining…" : "Explain PO mismatch"}</button>);
}

export default function InvestigatePage() {
  return <Suspense><Inner /></Suspense>;
}
