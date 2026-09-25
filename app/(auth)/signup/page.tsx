"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Briefcase, Laptop, User } from "lucide-react";
import { app, type Profile } from "@/lib/client";
import { ErrorNote } from "@/components/ui";

const TYPES: Array<{ value: Profile; label: string; hint: string; icon: typeof User }> = [
  { value: "individual", label: "Just me", hint: "Salary, bills, personal tax", icon: User },
  { value: "business", label: "I run a shop or business", hint: "GST, purchase bills, sales", icon: Briefcase },
  { value: "freelancer", label: "I freelance", hint: "Clients, invoices, advance tax", icon: Laptop },
];

export default function SignupPage() {
  const router = useRouter();
  const [f, setF] = useState({ name: "", email: "", password: "", profile_type: "individual" as Profile,
    business_name: "", gstin: "", state_code: "27" });
  const [states, setStates] = useState<Array<{ code: string; name: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { app.states().then(setStates).catch(() => undefined); }, []);
  const set = (k: keyof typeof f, v: string) => { setF((s) => ({ ...s, [k]: v })); setError(null); };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.name.trim()) return setError("Enter your name.");
    if (!/^\S+@\S+\.\S+$/.test(f.email)) return setError("Enter a valid email address.");
    if (f.password.length < 8) return setError("Use a password of at least 8 characters.");
    setBusy(true);
    try {
      await app.signup({ ...f, gstin: f.gstin.trim() || null, business_name: f.business_name.trim() || null });
      router.replace("/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <h1 className="text-2xl font-extrabold">Create your account</h1>
        <p className="text-ink-soft text-sm mt-1">Free. Takes a minute.</p>
      </div>
      <fieldset>
        <legend className="text-sm text-ink-soft mb-2">Which describes you?</legend>
        <div className="grid gap-2">
          {TYPES.map((t) => (
            <label key={t.value} className={`flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer transition ${f.profile_type === t.value ? "bg-base-deep shadow-neu-in ring-1 ring-accent/60" : "bg-base shadow-neu-sm"}`}>
              <input type="radio" name="pt" className="sr-only" checked={f.profile_type === t.value} onChange={() => set("profile_type", t.value)} />
              <t.icon className="w-5 h-5 text-accent-soft" aria-hidden />
              <span><span className="font-semibold block text-sm">{t.label}</span><span className="text-xs text-ink-soft">{t.hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="block"><span className="text-sm text-ink-soft">Your name</span>
        <input className="field mt-1.5" autoComplete="name" value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
      <label className="block"><span className="text-sm text-ink-soft">Email</span>
        <input className="field mt-1.5" type="email" autoComplete="email" value={f.email} onChange={(e) => set("email", e.target.value)} /></label>
      <label className="block"><span className="text-sm text-ink-soft">Password</span>
        <input className="field mt-1.5" type="password" autoComplete="new-password" value={f.password} onChange={(e) => set("password", e.target.value)} /></label>
      <label className="block"><span className="text-sm text-ink-soft">State</span>
        <select className="field mt-1.5" value={f.state_code} onChange={(e) => set("state_code", e.target.value)}>
          {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select></label>
      {f.profile_type !== "individual" && (
        <div className="grid sm:grid-cols-2 gap-3">
          <label className="block"><span className="text-sm text-ink-soft">Business name</span>
            <input className="field mt-1.5" value={f.business_name} onChange={(e) => set("business_name", e.target.value)} /></label>
          <label className="block"><span className="text-sm text-ink-soft">GSTIN (if registered)</span>
            <input className="field mt-1.5 uppercase" maxLength={15} value={f.gstin} onChange={(e) => set("gstin", e.target.value)} /></label>
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      <button className="btn-primary w-full py-3" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      <p className="text-sm text-ink-soft text-center">Already have one? <Link href="/login" className="text-accent-soft font-semibold">Sign in</Link></p>
    </form>
  );
}
