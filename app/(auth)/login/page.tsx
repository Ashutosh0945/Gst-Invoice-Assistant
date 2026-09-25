"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { app } from "@/lib/client";
import { ErrorNote } from "@/components/ui";

function LoginForm() {
  const router = useRouter();
  const next = useSearchParams().get("next") || "/app";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) { setError("Enter your email and password."); return; }
    setBusy(true);
    setError(null);
    try {
      await app.login(email, password);
      router.replace(next.startsWith("/app") ? next : "/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <h1 className="text-2xl font-extrabold">Welcome back</h1>
        <p className="text-ink-soft text-sm mt-1">Sign in to your bills, invoices and assistant.</p>
      </div>
      <label className="block"><span className="text-sm text-ink-soft">Email</span>
        <input className="field mt-1.5" type="email" autoComplete="email" value={email} onChange={(e) => { setEmail(e.target.value); setError(null); }} /></label>
      <label className="block"><span className="text-sm text-ink-soft">Password</span>
        <input className="field mt-1.5" type="password" autoComplete="current-password" value={password} onChange={(e) => { setPassword(e.target.value); setError(null); }} /></label>
      {error && <ErrorNote>{error}</ErrorNote>}
      <button className="btn-primary w-full py-3" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      <p className="text-sm text-ink-soft text-center">New here? <Link href="/signup" className="text-accent-soft font-semibold">Create an account</Link></p>
    </form>
  );
}

export default function LoginPage() {
  return <Suspense><LoginForm /></Suspense>;
}
