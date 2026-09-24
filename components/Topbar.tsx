"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";
import { Bell, PanelLeft, RefreshCw, Search, Upload } from "lucide-react";

export function Topbar() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="sticky top-0 z-20 bg-base/90 backdrop-blur border-b border-base-line/60">
      <div className="flex items-center gap-3 px-5 md:px-8 h-[72px]">
        <button aria-label="Toggle menu" className="icon-btn lg:hidden"
          onClick={() => window.dispatchEvent(new Event("toggle-sidebar"))}>
          <PanelLeft className="w-5 h-5" />
        </button>
        <form
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            router.push(`/invoices${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
          }}
          className="flex items-center gap-2 bg-base-deep shadow-neu-in rounded-xl px-3 h-11 w-full max-w-sm"
        >
          <Search className="w-4 h-4 text-ink-faint" aria-hidden />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search invoices"
            placeholder="Search invoice no., vendor, GSTIN…"
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-ink-faint" />
          <kbd className="hidden sm:block text-[11px] text-ink-faint bg-base px-1.5 py-0.5 rounded-md shadow-neu-sm">⌘K</kbd>
        </form>
        <div className="flex-1" />
        <Link href="/upload" className="btn-primary hidden sm:inline-flex">
          <Upload className="w-4 h-4" aria-hidden /> Upload
        </Link>
        <button aria-label="Refresh data" className="icon-btn" onClick={() => startTransition(() => router.refresh())}>
          <RefreshCw className={`w-[18px] h-[18px] ${pending ? "animate-spin" : ""}`} />
        </button>
        <Link href="/review" aria-label="Review queue" className="icon-btn relative">
          <Bell className="w-[18px] h-[18px]" />
          <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-bad" />
        </Link>
        <div className="hidden sm:grid w-11 h-11 rounded-xl bg-accent place-items-center text-sm font-bold shadow-glow" aria-label="Signed in as Accounts team">AT</div>
      </div>
    </header>
  );
}
