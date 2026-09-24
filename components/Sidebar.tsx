"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BadgeIndianRupee, BarChart3, Brain, ChevronDown, Copy, FileSearch, FileStack, GitCompareArrows,
  LayoutGrid, ListChecks, QrCode, ShieldCheck, Sparkles, Store, Upload, type LucideIcon,
} from "lucide-react";

type Item = { href: string; label: string; icon: LucideIcon };
type Group = { key: string; label: string; icon: LucideIcon; tone: string; items: Item[] };

const GROUPS: Group[] = [
  {
    key: "work", label: "Invoices", icon: FileStack, tone: "bg-accent/90",
    items: [
      { href: "/invoices", label: "All invoices", icon: FileSearch },
      { href: "/review", label: "Review queue", icon: ListChecks },
      { href: "/upload", label: "Upload invoice", icon: Upload },
    ],
  },
  {
    key: "compliance", label: "GST compliance", icon: ShieldCheck, tone: "bg-good/90",
    items: [
      { href: "/gstr2b", label: "GSTR-2B match", icon: GitCompareArrows },
      { href: "/itc", label: "Input tax credit", icon: BadgeIndianRupee },
      { href: "/einvoice", label: "E-invoice checks", icon: QrCode },
    ],
  },
  {
    key: "insights", label: "Insights", icon: BarChart3, tone: "bg-warn/90",
    items: [
      { href: "/vendors", label: "Vendor risk", icon: Store },
      { href: "/analytics", label: "GST analytics", icon: BarChart3 },
      { href: "/reconciliation", label: "PO matching", icon: GitCompareArrows },
      { href: "/duplicates", label: "Duplicates", icon: Copy },
      { href: "/model", label: "Model accuracy", icon: Brain },
    ],
  },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname() || "/";
  const [open, setOpen] = useState<Record<string, boolean>>({ work: true, compliance: true, insights: true });
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const toggle = () => setMobileOpen((v) => !v);
    window.addEventListener("toggle-sidebar", toggle);
    return () => window.removeEventListener("toggle-sidebar", toggle);
  }, []);
  useEffect(() => setMobileOpen(false), [pathname]);

  return (
    <>
      {mobileOpen && (
        <button aria-label="Close menu" onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/40 lg:hidden" />
      )}
      <aside
        className={`fixed lg:sticky top-0 z-40 h-screen w-[264px] shrink-0 bg-base-deep border-r border-base-line/60
          flex flex-col transition-transform lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        <div className="flex items-center gap-3 px-5 pt-6 pb-5">
          <div className="w-12 h-12 rounded-2xl bg-accent grid place-items-center shadow-glow">
            <Sparkles className="w-6 h-6 text-white" aria-hidden />
          </div>
          <div>
            <div className="text-lg font-bold leading-tight">GST Desk</div>
            <div className="label text-[10px] text-ink-faint">INVOICE AI</div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-4 space-y-4 pb-4" aria-label="Main">
          <NavLink item={{ href: "/", label: "Overview", icon: LayoutGrid }} active={pathname === "/"} />
          {GROUPS.map((g) => (
            <div key={g.key}>
              <button
                onClick={() => setOpen((o) => ({ ...o, [g.key]: !o[g.key] }))}
                aria-expanded={open[g.key]}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-2xl bg-base shadow-neu-sm"
              >
                <span className={`w-8 h-8 rounded-full grid place-items-center ${g.tone}`}>
                  <g.icon className="w-4 h-4 text-white" aria-hidden />
                </span>
                <span className="label flex-1 text-left">{g.label.toUpperCase()}</span>
                <ChevronDown className={`w-4 h-4 text-ink-faint transition-transform ${open[g.key] ? "" : "-rotate-90"}`} />
              </button>
              {open[g.key] && (
                <ul className="mt-1.5 space-y-0.5">
                  {g.items.map((it) => (
                    <li key={it.href}><NavLink item={it} active={isActive(pathname, it.href)} /></li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </nav>

        <div className="px-4 pb-4 pt-2 border-t border-base-line/40">
          <div className="flex items-center gap-3 px-3 py-3 rounded-2xl bg-base shadow-neu-sm">
            <div className="w-9 h-9 rounded-full bg-accent grid place-items-center text-sm font-bold">A</div>
            <div className="min-w-0">
              <div className="text-sm font-semibold truncate">Accounts team</div>
              <div className="text-xs text-ink-faint">Reviewer</div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}

function NavLink({ item, active }: { item: Item; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-3 px-3 py-[7px] rounded-xl text-[14px] transition ${
        active ? "bg-base shadow-neu-in text-white" : "text-ink-soft hover:text-white"
      }`}
    >
      <Icon className={`w-[18px] h-[18px] ${active ? "text-accent-soft" : ""}`} aria-hidden />
      {item.label}
    </Link>
  );
}
