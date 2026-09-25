"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Sparkles } from "lucide-react";
import { brand } from "@/lib/brand";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) return setError("Enter your email and password.");
    setBusy(true);
    setError(null);
    try {
      const r = await fetch("/api/v1/app/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }), credentials: "include" });
      if (!r.ok) throw new Error(r.status === 401 ? "Email or password is incorrect." : "Sign in failed. Try again.");
      const me = await fetch("/api/v1/console/me", { credentials: "include" });
      if (me.status === 403) {
        await fetch("/api/v1/app/auth/logout", { method: "POST", credentials: "include" });
        throw new Error("This account doesn't have console access. Ask an administrator to add you as staff.");
      }
      if (!me.ok) throw new Error("Sign in failed. Try again.");
      router.replace(next.startsWith("/") && !next.startsWith("//") ? next : "/");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-5">
      <form onSubmit={submit} className="w-full max-w-sm neu-card p-7 space-y-4 rise" noValidate>
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-2xl bg-accent grid place-items-center shadow-glow"><Sparkles className="w-6 h-6 text-white" aria-hidden /></div>
          <div><div className="text-lg font-bold leading-tight">{brand.name}</div><div className="label text-[10px] text-ink-faint">STAFF CONSOLE</div></div>
        </div>
        <label className="block"><span className="text-sm text-ink-soft">Email</span>
          <input className="field mt-1.5" type="email" autoComplete="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} /></label>
        <label className="block"><span className="text-sm text-ink-soft">Password</span>
          <input className="field mt-1.5" type="password" autoComplete="current-password" value={password} onChange={(e) => { setPassword(e.target.value); setError(null); }} /></label>
        {error && <p role="alert" className="text-sm text-bad">{error}</p>}
        <button className="btn-primary w-full py-3" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
