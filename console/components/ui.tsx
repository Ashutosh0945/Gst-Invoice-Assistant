import type { LucideIcon } from "lucide-react";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: string; right?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pt-8 pb-7 rise">
      <div>
        <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1.5 text-ink-soft max-w-2xl">{subtitle}</p>}
      </div>
      {right && <div className="flex items-center gap-3">{right}</div>}
    </header>
  );
}

export function Card({ title, action, children, className = "", pad = true }: {
  title?: React.ReactNode; action?: React.ReactNode; children: React.ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`neu-card min-w-0 ${pad ? "p-6" : ""} ${className}`}>
      {(title || action) && (
        <div className={`flex flex-wrap items-center justify-between gap-3 ${pad ? "mb-5" : "px-6 pt-6 mb-4"}`}>
          {title && <h2 className="text-lg font-bold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const TONE_TEXT = { accent: "text-accent-soft", good: "text-good", warn: "text-warn", bad: "text-bad", info: "text-info", muted: "text-ink-soft" };
export type Tone = keyof typeof TONE_TEXT;

export function Kpi({ icon: Icon, label, value, pill, tone = "accent", href }: {
  icon: LucideIcon; label: string; value: string; pill?: string; tone?: Tone; href?: string;
}) {
  const body = (
    <div className="neu-card p-6 h-full transition hover:-translate-y-0.5">
      <div className="flex items-start justify-between gap-2">
        <div className="icon-tile"><Icon className={`w-5 h-5 ${TONE_TEXT[tone]}`} aria-hidden /></div>
        {pill && (
          <span className={`pill ${TONE_TEXT[tone]}`}><ArrowUpRight className="w-3.5 h-3.5" aria-hidden />{pill}</span>
        )}
      </div>
      <div className="mt-6 text-[30px] font-extrabold tabular leading-none">{value}</div>
      <div className="label mt-3">{label.toUpperCase()}</div>
    </div>
  );
  return href ? <Link href={href} className="block rise">{body}</Link> : <div className="rise">{body}</div>;
}

export function StatTile({ icon: Icon, value, title, sub, tone = "accent", href }: {
  icon: LucideIcon; value: string; title: string; sub?: string; tone?: Tone; href?: string;
}) {
  const body = (
    <div className="neu-card p-5 flex items-center gap-4 transition hover:-translate-y-0.5">
      <div className="icon-tile shrink-0"><Icon className={`w-5 h-5 ${TONE_TEXT[tone]}`} aria-hidden /></div>
      <div className="min-w-0">
        <div className="text-2xl font-extrabold tabular leading-tight">{value}</div>
        <div className="font-semibold">{title}</div>
        {sub && <div className="text-xs text-ink-soft">{sub}</div>}
      </div>
    </div>
  );
  return href ? <Link href={href} className="block">{body}</Link> : body;
}

export function Empty({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="text-center py-12">
      <p className="font-semibold">{title}</p>
      {hint && <p className="text-sm text-ink-soft mt-1.5 max-w-md mx-auto">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Legend({ items }: { items: Array<{ label: string; color: string }> }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5 text-ink-soft">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: i.color }} />{i.label}
        </span>
      ))}
    </div>
  );
}

export function FilterChips({ base, param, current, options }: {
  base: string; param: string; current?: string; options: Array<{ value: string; label: string; count?: number }>;
}) {
  const all = [{ value: "", label: "All" }, ...options];
  return (
    <div className="flex flex-wrap gap-2">
      {all.map((o) => {
        const active = (current || "") === o.value;
        const href = o.value ? `${base}${base.includes("?") ? "&" : "?"}${param}=${o.value}` : base;
        return (
          <Link key={o.value || "all"} href={href}
            className={`px-3.5 py-1.5 rounded-xl text-sm transition ${active ? "bg-base shadow-neu-in text-white" : "bg-base shadow-neu-sm text-ink-soft hover:text-white"}`}>
            {o.label}{o.count !== undefined && <span className="ml-1.5 text-ink-faint tabular">{o.count}</span>}
          </Link>
        );
      })}
    </div>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  return <p role="alert" className="text-sm text-bad mt-3">{children}</p>;
}
