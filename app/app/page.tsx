"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertTriangle, BadgeIndianRupee, CalendarClock, HandCoins, MessagesSquare, Receipt, ShieldCheck, Wallet } from "lucide-react";
import { app, fmtDate, inr, inrShort, type BillRow, type Deadline, type Snapshot } from "@/lib/client";
import { useMe } from "@/components/AppShell";
import { Card, Empty, Kpi } from "@/components/ui";
import { BarList } from "@/components/charts";
import { BillUpload } from "@/components/BillUpload";

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

export default function Home() {
  const { me } = useMe();
  const [data, setData] = useState<{ snapshot: Snapshot; recent_bills: BillRow[]; deadlines: Deadline[]; suggestions: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { app.home().then(setData).catch((e) => setError(e.message)); }, []);

  if (error) return <div className="pt-10"><Card><Empty title="Couldn't load your home screen" hint={error} /></Card></div>;
  if (!data) return <Skeleton />;
  const s = data.snapshot;
  const next = data.deadlines[0];
  const biz = me.profile_type !== "individual";

  return (
    <div>
      <header className="flex flex-wrap items-end justify-between gap-4 pt-8 pb-6 rise">
        <div>
          <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">{greeting()}, {me.name.split(" ")[0]} 👋</h1>
          <p className="text-ink-soft mt-1">Here&apos;s your money and tax picture today</p>
        </div>
        <div className="text-sm text-ink-soft">{new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}</div>
      </header>

      <Link href="/app/assistant" className="block neu-card p-5 mb-6 hover:-translate-y-0.5 transition rise">
        <div className="flex items-center gap-4">
          <div className="icon-tile shrink-0"><MessagesSquare className="w-5 h-5 text-accent-soft" aria-hidden /></div>
          <div className="flex-1 min-w-0">
            <div className="font-bold">Ask your accountant</div>
            <div className="text-sm text-ink-soft truncate">Try: “{data.suggestions[0]}”</div>
          </div>
          <span className="btn-primary hidden sm:inline-flex">Ask</span>
        </div>
      </Link>

      <div className="grid gap-5 grid-cols-2 xl:grid-cols-4">
        <Kpi icon={Wallet} tone="accent" label="Spent this month" value={inrShort(s.spend_this_month)} pill={`${s.bills} bills`} href="/app/bills" />
        {biz ? (
          <Kpi icon={BadgeIndianRupee} tone="good" label="GST to claim back" value={inrShort(s.gst_claimable)} href="/app/bills" />
        ) : (
          <Kpi icon={ShieldCheck} tone={Number(s.overcharged_total) > 0 ? "bad" : "good"} label="Overcharges found" value={inr(s.overcharged_total)} href="/app/bills" />
        )}
        {biz ? (
          <Kpi icon={HandCoins} tone={s.overdue_invoices ? "bad" : "warn"} label="Owed to you" value={inrShort(s.owed_to_you)}
            pill={s.overdue_invoices ? `${s.overdue_invoices} overdue` : `${s.unpaid_invoices} unpaid`} href="/app/invoices" />
        ) : (
          <Kpi icon={Receipt} tone="info" label="Bills saved" value={String(s.bills)} href="/app/bills" />
        )}
        <Kpi icon={CalendarClock} tone={next && next.days_left <= 7 ? "bad" : "warn"} label={next ? next.title : "Next deadline"}
          value={next ? `${next.days_left} days` : "—"} pill={next ? fmtDate(next.date) : undefined} href="/app/tax" />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_380px] mt-6">
        <div className="space-y-6 min-w-0">
          <Card title="Add a bill"><BillUpload compact /></Card>
          <Card title="Recent bills" action={<Link href="/app/bills" className="text-sm text-accent-soft">All bills</Link>}>
            {data.recent_bills.length === 0 ? <Empty title="No bills yet" hint="Add your first bill above — a restaurant bill, a gadget invoice or a supplier bill." /> : (
              <ul className="space-y-3">
                {data.recent_bills.map((b) => (
                  <li key={b.id}>
                    <Link href={`/app/bills/${b.id}`} className="flex items-center gap-3 neu-tile p-3.5 hover:text-white">
                      <div className="icon-tile w-10 h-10 shrink-0"><Receipt className="w-4 h-4 text-accent-soft" aria-hidden /></div>
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold truncate">{b.vendor || b.file}</div>
                        <div className="text-xs text-ink-soft">{b.category_label} · {fmtDate(b.date)}</div>
                      </div>
                      <div className="font-bold tabular">{inr(b.total)}</div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          {s.warranties_expiring.length > 0 && (
            <Card title="Warranties ending soon">
              <ul className="space-y-2">
                {s.warranties_expiring.map((w) => (
                  <li key={w.bill_id}><Link href={`/app/bills/${w.bill_id}`} className="flex items-center gap-2 text-sm hover:text-white">
                    <AlertTriangle className="w-4 h-4 text-warn" aria-hidden /> {w.vendor ?? "Bill"} — ends {fmtDate(w.until)}</Link></li>
                ))}
              </ul>
            </Card>
          )}
          <Card title="Coming up">
            {data.deadlines.length === 0 ? <Empty title="No deadlines soon" /> : (
              <ul className="space-y-3">
                {data.deadlines.map((d) => (
                  <li key={d.date + d.title} className="flex items-center gap-3">
                    <div className={`w-12 text-center rounded-xl py-1.5 ${d.days_left <= 7 ? "bg-bad/15 text-bad" : "bg-base shadow-neu-sm"}`}>
                      <div className="text-lg font-extrabold leading-none">{new Date(`${d.date}T00:00:00`).getDate()}</div>
                      <div className="text-[10px] uppercase">{new Date(`${d.date}T00:00:00`).toLocaleDateString("en-IN", { month: "short" })}</div>
                    </div>
                    <div className="min-w-0"><div className="font-semibold text-sm">{d.title}</div><div className="text-xs text-ink-soft">{d.detail}</div></div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Where your money went">
            {s.spend_by_category.length === 0 ? <Empty title="Add bills to see this" /> :
              <BarList format={(n) => inrShort(n)} rows={s.spend_by_category.slice(0, 6).map((c) => ({ label: c.category, value: Number(c.amount) }))} />}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="pt-8 space-y-6 animate-pulse" aria-label="Loading">
      <div className="h-10 w-72 rounded-xl bg-base-raised" />
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-5">{[0, 1, 2, 3].map((i) => <div key={i} className="h-40 neu-card" />)}</div>
      <div className="h-64 neu-card" />
    </div>
  );
}
