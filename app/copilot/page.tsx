"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Bot, Check, ClipboardCopy, Database, Loader2, SendHorizontal, ShieldCheck, Trash2 } from "lucide-react";
import { ai, type Card, type CopilotReply } from "@/lib/ai";

type Msg = { id: number; role: "user" | "assistant"; content: string; reply?: CopilotReply; error?: boolean };
const DEFAULT_Q = ["Give me this month's GST summary", "How much ITC is currently at risk?", "Which vendor has the most GST errors?",
  "Show invoices with GSTR-2B mismatches", "Which vendors need attention?", "What needs my attention right now?"];

function CopilotInner() {
  const params = useSearchParams();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [ctx, setCtx] = useState<unknown>(null);
  const end = useRef<HTMLDivElement>(null);
  const asked = useRef(false);

  async function send(q: string) {
    const message = q.trim();
    if (!message || busy) return;
    setText("");
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { id: Date.now(), role: "user", content: message }]);
    setBusy(true);
    try {
      const reply = await ai.copilot(message, history, ctx);
      setCtx(reply.context);
      setMsgs((m) => [...m, { id: Date.now() + 1, role: "assistant", content: reply.answer, reply }]);
    } catch (e) {
      setMsgs((m) => [...m, { id: Date.now() + 1, role: "assistant", content: e instanceof Error ? e.message : "Something went wrong.", error: true }]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const q = params.get("q");
    if (q && !asked.current) { asked.current = true; send(q); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  const last = [...msgs].reverse().find((m) => m.reply)?.reply;
  const suggestions = last?.followups?.length ? last.followups : DEFAULT_Q;

  return (
    <div className="flex flex-col h-[calc(100dvh-72px)] pt-6 pb-4">
      <div className="flex items-start justify-between gap-3 pb-4">
        <div>
          <h1 className="text-[28px] font-extrabold tracking-tight">AI Copilot</h1>
          <p className="text-ink-soft text-sm mt-1">Ask about your GST data. Every number comes from your records and is fact-checked; the AI only words the answer.</p>
        </div>
        {msgs.length > 0 && <button className="btn py-1.5" onClick={() => { setMsgs([]); setCtx(null); }}><Trash2 className="w-4 h-4" aria-hidden />Clear</button>}
      </div>

      <div className="flex-1 overflow-y-auto neu-inset p-4 md:p-6 space-y-5" aria-live="polite">
        {msgs.length === 0 && (
          <div className="text-center py-10">
            <div className="icon-tile mx-auto w-14 h-14"><Bot className="w-6 h-6 text-accent-soft" aria-hidden /></div>
            <p className="font-bold text-lg mt-4">What would you like to know?</p>
            <p className="text-sm text-ink-soft mt-1">Pick a question or type your own.</p>
          </div>
        )}
        {msgs.map((m) => m.role === "user"
          ? <div key={m.id} className="ml-auto max-w-[85%] w-fit bg-accent text-white rounded-2xl rounded-br-md px-4 py-2.5">{m.content}</div>
          : <Answer key={m.id} m={m} />)}
        {busy && <div className="flex items-center gap-2 text-sm text-ink-soft"><Loader2 className="w-4 h-4 animate-spin" aria-hidden /> Checking your data…</div>}
        <div ref={end} />
      </div>

      <div className="pt-3">
        <div className="flex gap-2 overflow-x-auto pb-3">
          {suggestions.map((s) => <button key={s} disabled={busy} onClick={() => send(s)} className="shrink-0 px-3.5 py-2 rounded-xl text-sm bg-base shadow-neu-sm text-ink-soft hover:text-ink-strong">{s}</button>)}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); send(text); }} className="flex gap-2">
          <input value={text} onChange={(e) => setText(e.target.value)} className="field py-3" placeholder="e.g. Which vendors have GSTR-2B mismatches this month?" aria-label="Your question" maxLength={1000} />
          <button className="btn-primary px-4" disabled={busy || !text.trim()} aria-label="Ask"><SendHorizontal className="w-5 h-5" /></button>
        </form>
      </div>
    </div>
  );
}

function Answer({ m }: { m: Msg }) {
  const [copied, setCopied] = useState(false);
  const [showData, setShowData] = useState(false);
  const r = m.reply;
  return (
    <div className="max-w-[95%] space-y-2">
      <div className={`rounded-2xl rounded-bl-md px-4 py-3 whitespace-pre-wrap leading-relaxed ${m.error ? "bg-bad/10 text-bad" : "bg-base shadow-neu-sm"}`}>{m.content}</div>
      {r && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
            <span className="inline-flex items-center gap-1 rounded-lg bg-base-deep px-2 py-1">
              <ShieldCheck className="w-3 h-3 text-good" aria-hidden />
              {r.answer_source === "ai" ? "AI wording · numbers verified against your data" : "Rule-based answer from your data"}
            </span>
            {r.note && <span>{r.note}</span>}
            <button className="inline-flex items-center gap-1 hover:text-ink-strong" onClick={() => { navigator.clipboard?.writeText(m.content); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
              {copied ? <Check className="w-3 h-3" /> : <ClipboardCopy className="w-3 h-3" />}{copied ? "Copied" : "Copy"}
            </button>
            <button className="inline-flex items-center gap-1 hover:text-ink-strong" onClick={() => setShowData((v) => !v)}>
              <Database className="w-3 h-3" />{showData ? "Hide source data" : "View source data"}
            </button>
          </div>
          {r.cards.map((c, i) => <DataCard key={i} c={c} />)}
          {showData && <pre className="text-xs neu-inset p-3 overflow-x-auto max-h-72">{JSON.stringify(r.facts, null, 2)}</pre>}
        </>
      )}
    </div>
  );
}

function DataCard({ c }: { c: Card }) {
  if (c.type === "link") return <Link href={c.href || "#"} className="btn">{c.title}</Link>;
  if (c.type === "kpis") return (
    <div className="neu-card p-4">
      <div className="text-sm font-semibold mb-3">{c.title}</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {(c.items || []).map(([l, v]) => <div key={l} className="neu-inset p-3"><div className="text-xs text-ink-soft">{l}</div><div className="font-bold tabular">{v}</div></div>)}
      </div>
    </div>
  );
  if (!c.rows?.length) return null;
  return (
    <div className="neu-card p-4">
      <div className="flex justify-between items-center mb-2"><div className="text-sm font-semibold">{c.title}</div>
        {c.link && <Link href={c.link} className="text-xs text-accent-soft">Open page</Link>}</div>
      <div className="overflow-x-auto -mx-3">
        <table className="tbl">
          <thead><tr>{c.columns?.map((h) => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{c.rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j} className={j === 0 ? "font-semibold" : "text-ink-soft"}>
              {j === 0 && c.row_links?.[i] ? <Link href={c.row_links[i]} className="hover:text-accent-soft">{cell ?? "—"}</Link> : cell ?? "—"}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

export default function CopilotPage() {
  return <Suspense><CopilotInner /></Suspense>;
}
