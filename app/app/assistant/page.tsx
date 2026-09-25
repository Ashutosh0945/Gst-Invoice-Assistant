"use client";

import { useEffect, useRef, useState } from "react";
import { Calculator, Loader2, SendHorizontal, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { app, inr, type ChatMsg } from "@/lib/client";
import { brand } from "@/lib/brand";

const TOOL_LABELS: Record<string, string> = {
  financial_snapshot: "Your bills & invoices", compare_tax_regimes: "Income tax calculator (FY slabs)",
  check_gst_registration: "GST registration rules", advance_tax_plan: "Advance tax schedule",
  presumptive_income: "Presumptive tax rules", upcoming_deadlines: "Tax calendar", search_bills: "Your bills",
  unpaid_invoices: "Your invoices", deduction_hints: "Deduction rules",
};

export default function Assistant() {
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => { app.chatHistory().then((h) => { setMsgs(h.messages); setSuggestions(h.suggestions); }).catch((e) => setError(e.message)); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  async function send(q: string) {
    const message = q.trim();
    if (!message || busy) return;
    setText("");
    setError(null);
    setMsgs((m) => [...m, { id: `local-${Date.now()}`, role: "user", content: message }]);
    setBusy(true);
    try {
      const reply = await app.ask(message);
      setMsgs((m) => [...m, reply]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The assistant couldn't answer. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-4rem-5.5rem)] lg:h-[calc(100dvh-2rem)] pt-4 lg:pt-8">
      <div className="flex items-center justify-between gap-3 pb-4">
        <div>
          <h1 className="text-2xl font-extrabold">Ask your accountant</h1>
          <p className="text-sm text-ink-soft">Answers use your own bills and this year&apos;s official tax rules. {brand.name} is an AI, not a CA — for notices, audits or disputes, see a professional.</p>
        </div>
        {msgs.length > 0 && (
          <button className="btn py-1.5" onClick={async () => { await app.clearChat(); setMsgs([]); }}>
            <Trash2 className="w-4 h-4" aria-hidden /><span className="hidden sm:inline">Clear</span>
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto neu-inset p-4 md:p-6 space-y-4" aria-live="polite">
        {msgs.length === 0 && !busy && (
          <div className="text-center py-10">
            <div className="icon-tile mx-auto w-14 h-14"><Sparkles className="w-6 h-6 text-accent-soft" aria-hidden /></div>
            <p className="font-bold mt-4">What would you like to know?</p>
            <p className="text-sm text-ink-soft mt-1">Tap a question to start.</p>
          </div>
        )}
        {msgs.map((m) => <Message key={m.id} m={m} />)}
        {busy && <div className="flex items-center gap-2 text-sm text-ink-soft"><Loader2 className="w-4 h-4 animate-spin" aria-hidden /> Working it out…</div>}
        <div ref={end} />
      </div>

      <div className="pt-3 pb-2">
        <div className="flex gap-2 overflow-x-auto pb-3 -mx-1 px-1">
          {suggestions.map((s) => (
            <button key={s} className="shrink-0 px-3.5 py-2 rounded-xl text-sm bg-base shadow-neu-sm text-ink-soft hover:text-white" onClick={() => send(s)} disabled={busy}>{s}</button>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} className="field py-3" placeholder="Ask about tax, GST, your bills…" aria-label="Your question" maxLength={2000} />
          <button className="btn-primary px-4" disabled={busy || !text.trim()} aria-label="Send"><SendHorizontal className="w-5 h-5" /></button>
        </form>
        {error && <p role="alert" className="text-sm text-bad mt-2">{error}</p>}
      </div>
    </div>
  );
}

function Message({ m }: { m: ChatMsg }) {
  if (m.role === "user") {
    return <div className="ml-auto max-w-[85%] w-fit bg-accent text-white rounded-2xl rounded-br-md px-4 py-2.5 text-[15px]">{m.content}</div>;
  }
  const tools = m.meta?.tools ?? [];
  const cmp = m.meta?.cards?.find((c) => c.tool === "compare_tax_regimes" && (c.result as { old?: unknown }).old)?.result as
    | { old: { total_tax: number }; new: { total_tax: number }; better: string; financial_year: string } | undefined;
  return (
    <div className="max-w-[92%]">
      <div className="bg-base shadow-neu-sm rounded-2xl rounded-bl-md px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap">{m.content}</div>
      {cmp && (
        <div className="grid grid-cols-2 gap-2 mt-2 max-w-sm">
          {(["new", "old"] as const).map((r) => (
            <div key={r} className={`rounded-xl p-3 ${cmp.better === r ? "bg-good/10 ring-1 ring-good/40" : "bg-base-deep"}`}>
              <div className="text-xs text-ink-soft">{r === "new" ? "New regime" : "Old regime"}</div>
              <div className="font-bold tabular">{inr(cmp[r].total_tax)}</div>
              {cmp.better === r && <div className="text-[11px] text-good">Better for you</div>}
            </div>
          ))}
        </div>
      )}
      {tools.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-2">
          {tools.map((t, i) => (
            <span key={i} className="inline-flex items-center gap-1 text-[11px] text-ink-soft bg-base-deep rounded-lg px-2 py-1">
              <Calculator className="w-3 h-3 text-good" aria-hidden />{TOOL_LABELS[t.tool] ?? t.tool}
            </span>
          ))}
          <span className="inline-flex items-center gap-1 text-[11px] text-ink-faint px-1 py-1">
            <ShieldCheck className="w-3 h-3" aria-hidden />{m.meta?.mode === "ai" ? "AI wording, calculated figures" : "Calculated answer"}
          </span>
        </div>
      )}
    </div>
  );
}
