"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  AlertOctagon, BadgeIndianRupee, Bot, CheckCircle2, Eye, FileStack, GitCompareArrows, Loader2, MessageSquareText,
  ReceiptIndianRupee, RefreshCw, Search, SendHorizontal, ShieldCheck, Siren, Sparkles, Upload, Wallet, Wifi, WifiOff, XCircle,
} from "lucide-react";
import { ai, inr, inrShort, type Brief, type Kpis, type RiskItem } from "@/lib/ai";
import { StackedBars } from "@/components/charts";

const PERIODS: Array<[string, string]> = [["this_month", "This month"], ["last_month", "Last month"], ["this_fy", "This FY"], ["all", "All time"]];
const SUGGEST = ["How much ITC is currently at risk?", "Which vendor has the most GST errors?", "Show invoices with GSTR-2B mismatches",
  "Give me this month's GST summary", "Which vendors need attention?"];
const SEV_CLS: Record<string, string> = { Critical: "text-bad bg-bad/10", High: "text-warn bg-warn/10", Review: "text-info bg-info/10" };

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function CommandCenter() {
  const router = useRouter();
  const [period, setPeriod] = useState("all");
  const [k, setK] = useState<Kpis | null>(null);
  const [risks, setRisks] = useState<{ items: RiskItem[]; counts: Record<string, number> } | null>(null);
  const [monthly, setMonthly] = useState<Array<{ month: string; purchase_value: number; gst: number }>>([]);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [q, setQ] = useState("");
  const [online, setOnline] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOnline(navigator.onLine);
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  useEffect(() => { setK(null); ai.kpis(period).then(setK).catch((e) => setError(e.message)); }, [period]);
  useEffect(() => {
    ai.risks().then(setRisks).catch(() => undefined);
    ai.monthly().then(setMonthly).catch(() => undefined);
  }, []);

  const genBrief = async () => {
    setBriefBusy(true);
    try { setBrief(await ai.brief(period === "all" ? "this_month" : period)); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); } finally { setBriefBusy(false); }
  };
  const ask = (text: string) => { if (text.trim()) router.push(`/copilot?q=${encodeURIComponent(text.trim())}`); };
  const openIssues = risks ? risks.items.length : null;

  const KPIS: Array<{ label: string; value: string; href: string; icon: typeof FileStack; tone: string; sub?: string; full?: string }> = k ? [
    { label: "Total invoices", value: String(k.total_invoices), href: "/invoices", icon: FileStack, tone: "text-accent-soft", sub: `${k.needs_review} need review` },
    { label: "Purchase value", value: inrShort(k.total_purchase_value), full: inr(k.total_purchase_value), href: "/analytics", icon: Wallet, tone: "text-info" },
    { label: "GST amount", value: inrShort(k.gst_amount), full: inr(k.gst_amount), href: "/analytics", icon: ReceiptIndianRupee, tone: "text-info" },
    { label: "ITC claimable", value: inrShort(k.itc_eligible), full: inr(k.itc_eligible), href: "/itc", icon: BadgeIndianRupee, tone: "text-good", sub: `${inr(k.itc_at_risk)} at risk` },
    { label: "GSTR-2B matched", value: String(k.gstr2b_matched), href: "/gstr2b", icon: CheckCircle2, tone: "text-good", sub: k.gstr2b_imported ? undefined : "No GSTR-2B imported" },
    { label: "GSTR-2B mismatches", value: String(k.gstr2b_mismatches), href: "/gstr2b", icon: XCircle, tone: k.gstr2b_mismatches ? "text-bad" : "text-good" },
    { label: "Open issues", value: openIssues === null ? "…" : String(openIssues), href: "/risk", icon: Siren, tone: openIssues ? "text-warn" : "text-good",
      sub: risks ? `${risks.counts.Critical} critical` : undefined },
  ] : [];

  return (
    <div>
      <header className="flex flex-wrap items-end justify-between gap-4 pt-8 pb-6">
        <div>
          <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">{greeting()} 👋</h1>
          <p className="text-ink-soft mt-1">Your GST intelligence command center</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg ${online ? "text-good bg-good/10" : "text-warn bg-warn/10"}`} role="status">
            {online ? <Wifi className="w-3.5 h-3.5" aria-hidden /> : <WifiOff className="w-3.5 h-3.5" aria-hidden />}{online ? "Online" : "Offline"}
          </span>
          <div className="flex gap-1 p-1 rounded-xl bg-base-deep shadow-neu-in" role="radiogroup" aria-label="Period">
            {PERIODS.map(([v, l]) => (
              <button key={v} role="radio" aria-checked={period === v} onClick={() => setPeriod(v)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium ${period === v ? "bg-base shadow-neu-sm text-ink-strong" : "text-ink-soft"}`}>{l}</button>
            ))}
          </div>
        </div>
      </header>

      {error && <div role="alert" className="neu-card p-4 mb-6 text-bad text-sm">{error} <button className="underline ml-2" onClick={() => location.reload()}>Retry</button></div>}

      <div className="grid gap-4 grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
        {k ? KPIS.map((c) => (
          <Link key={c.label} href={c.href} className="neu-card p-4 hover:-translate-y-0.5 transition block">
            <c.icon className={`w-5 h-5 ${c.tone}`} aria-hidden />
            <div className="text-xl font-extrabold tabular mt-3 truncate" title={c.full || c.value}>{c.value}</div>
            <div className="text-xs text-ink-soft mt-1">{c.label}</div>
            {c.sub && <div className="text-[11px] text-ink-faint mt-0.5 truncate">{c.sub}</div>}
          </Link>
        )) : Array.from({ length: 7 }).map((_, i) => <div key={i} className="neu-card h-[118px] animate-pulse" />)}
      </div>

      <section className="neu-card p-5 mt-6">
        <div className="flex items-center gap-2 font-bold"><Bot className="w-5 h-5 text-accent-soft" aria-hidden />What would you like to know?</div>
        <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="flex gap-2 mt-3">
          <input value={q} onChange={(e) => setQ(e.target.value)} className="field py-3" placeholder="Ask about GST errors, ITC at risk, GSTR-2B, vendors…" aria-label="Ask the AI Copilot" />
          <button className="btn-primary px-4" aria-label="Ask"><SendHorizontal className="w-5 h-5" /></button>
        </form>
        <div className="flex gap-2 overflow-x-auto mt-3 pb-1">
          {SUGGEST.map((s) => <button key={s} onClick={() => ask(s)} className="shrink-0 px-3 py-1.5 rounded-xl text-sm bg-base shadow-neu-sm text-ink-soft hover:text-ink-strong">{s}</button>)}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_420px] mt-6">
        <section className="neu-card p-5 min-w-0">
          <div className="flex items-center justify-between">
            <h2 className="font-bold text-lg flex items-center gap-2"><Siren className="w-5 h-5 text-warn" aria-hidden />Priority center</h2>
            <Link href="/risk" className="text-sm text-accent-soft">All issues</Link>
          </div>
          {!risks ? <div className="space-y-3 mt-4 animate-pulse">{[0, 1, 2].map((i) => <div key={i} className="h-16 neu-inset" />)}</div>
            : risks.items.length === 0 ? <p className="text-center py-10 font-semibold">Nothing needs your attention. 🎉</p>
            : <ul className="space-y-3 mt-4">{risks.items.slice(0, 5).map((x) => (
                <li key={x.key} className="neu-inset p-3.5">
                  <div className="flex flex-wrap items-start gap-2">
                    <span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold ${SEV_CLS[x.severity]}`}>{x.severity}</span>
                    <div className="flex-1 min-w-[180px]"><div className="font-semibold text-sm">{x.title}</div>
                      <div className="text-xs text-ink-soft">{x.invoice_number || x.vendor} · {x.reason}</div></div>
                    {x.amount_at_stake !== null && <div className="text-sm tabular font-semibold">{inr(x.amount_at_stake)}</div>}
                  </div>
                  {x.invoice_id && <div className="flex gap-3 mt-2 text-xs">
                    <Link href={`/invoices/${x.invoice_id}`} className="inline-flex items-center gap-1 text-accent-soft"><Eye className="w-3.5 h-3.5" aria-hidden />View</Link>
                    <Link href={`/invoices/${x.invoice_id}/investigate`} className="inline-flex items-center gap-1 text-accent-soft"><Search className="w-3.5 h-3.5" aria-hidden />Investigate</Link>
                    <Link href={`/invoices/${x.invoice_id}/investigate?explain=1`} className="inline-flex items-center gap-1 text-accent-soft"><MessageSquareText className="w-3.5 h-3.5" aria-hidden />Explain</Link>
                  </div>}
                </li>))}</ul>}
        </section>

        <section className="neu-card p-5">
          <h2 className="font-bold text-lg flex items-center gap-2"><Sparkles className="w-5 h-5 text-accent-soft" aria-hidden />AI CFO brief</h2>
          {!brief ? (
            <div className="mt-3">
              <p className="text-sm text-ink-soft">A short business, GST and ITC brief written from your actual numbers.</p>
              <button className="btn-primary mt-4" onClick={genBrief} disabled={briefBusy}>
                {briefBusy ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden />Writing…</> : "Generate full brief"}</button>
            </div>
          ) : (
            <div className="mt-3 space-y-4">
              <div>
                <div className="label mb-2">CALCULATED FROM YOUR DATA · {brief.facts.period.toUpperCase()}</div>
                <dl className="grid grid-cols-2 gap-2 text-sm">
                  {([["Invoices", brief.facts.period_kpis.total_invoices], ["Purchases", inr(brief.facts.period_kpis.total_purchase_value)],
                     ["GST", inr(brief.facts.period_kpis.gst_amount)], ["ITC claimable", inr(brief.facts.period_kpis.itc_eligible)],
                     ["ITC at risk", inr(brief.facts.period_kpis.itc_at_risk)], ["Critical issues", brief.facts.issue_counts.Critical]] as Array<[string, string | number]>).map(([l, v]) => (
                    <div key={l} className="neu-inset p-2.5"><dt className="text-[11px] text-ink-soft">{l}</dt><dd className="font-bold tabular">{v}</dd></div>))}
                </dl>
              </div>
              <div>
                <div className="label mb-2 flex items-center gap-1"><ShieldCheck className="w-3.5 h-3.5 text-good" aria-hidden />
                  {brief.commentary.source === "ai" ? "AI COMMENTARY (NUMBERS VERIFIED)" : "SUMMARY (RULE-BASED)"}</div>
                <p className="text-sm whitespace-pre-wrap leading-relaxed">{brief.commentary.text}</p>
                {brief.commentary.note && <p className="text-[11px] text-ink-faint mt-1">{brief.commentary.note}</p>}
              </div>
              <button className="btn py-1.5" onClick={genBrief} disabled={briefBusy}><RefreshCw className={`w-4 h-4 ${briefBusy ? "animate-spin" : ""}`} aria-hidden />Regenerate</button>
            </div>
          )}
        </section>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_420px] mt-6">
        <section className="neu-card p-5 min-w-0">
          <h2 className="font-bold text-lg">Purchases and GST by month</h2>
          {monthly.length === 0 ? <p className="text-sm text-ink-soft py-10 text-center">No invoices yet.</p> : (
            <div className="mt-4"><StackedBars data={monthly.map((m) => ({ label: new Date(`${m.month}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short" }),
              purchases: m.purchase_value - m.gst, gst: m.gst }))} format={(n) => inr(n)}
              series={[{ key: "purchases", label: "Purchases (before GST)", color: "rgb(var(--c-accent))" }, { key: "gst", label: "GST", color: "rgb(var(--c-good))" }]} /></div>
          )}
        </section>
        <section className="neu-card p-5">
          <h2 className="font-bold text-lg">Quick actions</h2>
          <div className="grid grid-cols-2 gap-3 mt-4">
            {([["/upload", Upload, "Upload invoice"], ["/invoices", Search, "Investigate invoice"], ["/gstr2b", GitCompareArrows, "Reconcile GSTR-2B"],
               ["/copilot", Bot, "Ask AI"], ["/risk", AlertOctagon, "Run risk analysis"], ["/reports", FileStack, "Monthly report"]] as const).map(([href, Icon, label]) => (
              <Link key={href + label} href={href} className="neu-tile p-3.5 flex items-center gap-2.5 text-sm hover:text-ink-strong">
                <Icon className="w-4 h-4 text-accent-soft" aria-hidden />{label}</Link>))}
            <button onClick={genBrief} className="neu-tile p-3.5 flex items-center gap-2.5 text-sm hover:text-ink-strong text-left">
              <Sparkles className="w-4 h-4 text-accent-soft" aria-hidden />Generate CFO brief</button>
          </div>
        </section>
      </div>
    </div>
  );
}
