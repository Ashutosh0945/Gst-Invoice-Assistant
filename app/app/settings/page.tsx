"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { app, type Profile } from "@/lib/client";
import { useMe } from "@/components/AppShell";
import { brand } from "@/lib/brand";
import { Card, ErrorNote } from "@/components/ui";

export default function Settings() {
  const { me, refreshMe } = useMe();
  const router = useRouter();
  const [f, setF] = useState({ name: me.name, profile_type: me.profile_type as Profile, business_name: me.business_name ?? "",
    gstin: me.gstin ?? "", state_code: me.state_code ?? "27" });
  const [states, setStates] = useState<Array<{ code: string; name: string }>>([]);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { app.states().then(setStates).catch(() => undefined); }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setMsg(null);
    try { await app.updateMe(f as never); await refreshMe(); setMsg("Saved."); }
    catch (err) { setError(err instanceof Error ? err.message : "Couldn't save."); }
    finally { setBusy(false); }
  }

  return (
    <div className="max-w-2xl">
      <h1 className="text-[28px] font-extrabold tracking-tight pt-8 pb-6">Settings</h1>
      <form onSubmit={save}>
        <Card title="Your profile">
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="block"><span className="text-sm text-ink-soft">Name</span>
              <input className="field mt-1.5" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
            <label className="block"><span className="text-sm text-ink-soft">Email</span>
              <input className="field mt-1.5 opacity-60" value={me.email} disabled /></label>
            <label className="block"><span className="text-sm text-ink-soft">I am</span>
              <select className="field mt-1.5" value={f.profile_type} onChange={(e) => setF({ ...f, profile_type: e.target.value as Profile })}>
                <option value="individual">An individual</option><option value="business">Running a shop / business</option><option value="freelancer">A freelancer</option>
              </select></label>
            <label className="block"><span className="text-sm text-ink-soft">State</span>
              <select className="field mt-1.5" value={f.state_code} onChange={(e) => setF({ ...f, state_code: e.target.value })}>
                {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
              </select></label>
            {f.profile_type !== "individual" && <>
              <label className="block"><span className="text-sm text-ink-soft">Business name (shown on invoices)</span>
                <input className="field mt-1.5" value={f.business_name} onChange={(e) => setF({ ...f, business_name: e.target.value })} /></label>
              <label className="block"><span className="text-sm text-ink-soft">GSTIN</span>
                <input className="field mt-1.5 uppercase" maxLength={15} value={f.gstin} onChange={(e) => setF({ ...f, gstin: e.target.value })} placeholder="Leave empty if not registered" /></label>
            </>}
          </div>
          {error && <ErrorNote>{error}</ErrorNote>}
          {msg && <p className="text-sm text-good mt-3">{msg}</p>}
          <button className="btn-primary mt-5" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button>
        </Card>
      </form>
      <Card className="mt-6" title="About">
        <p className="text-sm text-ink-soft">{brand.name} is an AI assistant, not a chartered accountant. Tax figures come from
          official rules for the current financial year; for notices, audits, disputes or complex cases, consult a qualified professional.</p>
        <button className="btn mt-5 text-bad" onClick={async () => { await app.logout().catch(() => undefined); router.replace("/login"); }}>
          <LogOut className="w-4 h-4" aria-hidden />Sign out</button>
      </Card>
    </div>
  );
}
