"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Calculator, FileText, Home, LogOut, MessagesSquare, Receipt, Settings, type LucideIcon } from "lucide-react";
import { app, type Me } from "@/lib/client";
import { brand } from "@/lib/brand";
import { Logo } from "@/components/Logo";

type Ctx = { me: Me; refreshMe: () => Promise<void> };
const MeContext = createContext<Ctx | null>(null);
export function useMe(): Ctx {
  const c = useContext(MeContext);
  if (!c) throw new Error("useMe outside AppShell");
  return c;
}

type Nav = { href: string; label: string; icon: LucideIcon; show?: (m: Me) => boolean };
const NAV: Nav[] = [
  { href: "/app", label: "Home", icon: Home },
  { href: "/app/assistant", label: "Ask", icon: MessagesSquare },
  { href: "/app/bills", label: "Bills", icon: Receipt },
  { href: "/app/invoices", label: "Invoices", icon: FileText, show: (m) => m.profile_type !== "individual" },
  { href: "/app/tax", label: "Tax", icon: Calculator },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/app";
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const refreshMe = useCallback(async () => { setMe(await app.me()); }, []);
  useEffect(() => { refreshMe().catch(() => undefined); }, [refreshMe]);

  if (!me) {
    return <div className="min-h-screen grid place-items-center"><div className="w-10 h-10 rounded-full border-2 border-accent border-t-transparent animate-spin" aria-label="Loading" /></div>;
  }
  const items = NAV.filter((n) => !n.show || n.show(me));
  const active = (href: string) => (href === "/app" ? pathname === "/app" : pathname.startsWith(href));

  return (
    <MeContext.Provider value={{ me, refreshMe }}>
      <div className="flex min-h-screen">
        <aside className="hidden lg:flex sticky top-0 h-screen w-[248px] shrink-0 flex-col bg-base-deep border-r border-base-line/60 px-4 py-6">
          <div className="px-1 mb-8"><Logo sub="AI ACCOUNTANT" /></div>
          <nav className="flex-1 space-y-1" aria-label="Main">
            {items.map((n) => (
              <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}
                className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl transition ${active(n.href) ? "bg-base shadow-neu-in text-white" : "text-ink-soft hover:text-white"}`}>
                <n.icon className={`w-[18px] h-[18px] ${active(n.href) ? "text-accent-soft" : ""}`} aria-hidden />{n.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-3 px-3 py-3 rounded-2xl bg-base shadow-neu-sm">
            <div className="w-9 h-9 rounded-full bg-accent grid place-items-center text-sm font-bold shrink-0">{me.name.slice(0, 1).toUpperCase()}</div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold truncate">{me.name}</div>
              <div className="text-xs text-ink-faint capitalize">{me.profile_type === "business" ? "Business" : me.profile_type}</div>
            </div>
            <button aria-label="Sign out" className="text-ink-faint hover:text-white"
              onClick={async () => { await app.logout().catch(() => undefined); router.replace("/login"); }}>
              <LogOut className="w-4 h-4" />
            </button>
          </div>
          {brand.poweredBy && <p className="text-[10px] text-ink-faint text-center mt-3">Numbers from verified tax rules</p>}
        </aside>

        <div className="flex-1 min-w-0 pb-24 lg:pb-10">
          <header className="lg:hidden sticky top-0 z-20 bg-base/90 backdrop-blur border-b border-base-line/60 px-4 h-16 flex items-center justify-between"
            style={{ paddingTop: "env(safe-area-inset-top)" }}>
            <Logo size="sm" />
            <Link href="/app/settings" className="w-9 h-9 rounded-full bg-accent grid place-items-center text-sm font-bold" aria-label="Settings">
              {me.name.slice(0, 1).toUpperCase()}
            </Link>
          </header>
          <main className="px-4 md:px-8 max-w-6xl mx-auto">{children}</main>
        </div>

        <nav className="lg:hidden fixed bottom-0 inset-x-0 z-30 bg-base-deep/95 backdrop-blur border-t border-base-line/60 grid"
          style={{ gridTemplateColumns: `repeat(${items.length - 1}, 1fr)`, paddingBottom: "env(safe-area-inset-bottom)" }} aria-label="Main">
          {items.filter((n) => n.href !== "/app/settings").map((n) => (
            <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}
              className={`flex flex-col items-center gap-1 py-2.5 text-[11px] ${active(n.href) ? "text-white" : "text-ink-faint"}`}>
              <span className={`w-10 h-8 grid place-items-center rounded-xl ${active(n.href) ? "bg-base shadow-neu-in" : ""}`}>
                <n.icon className={`w-5 h-5 ${active(n.href) ? "text-accent-soft" : ""}`} aria-hidden />
              </span>{n.label}
            </Link>
          ))}
        </nav>
      </div>
    </MeContext.Provider>
  );
}
