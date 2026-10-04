"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, CircleHelp, CloudOff, Database, KeyRound, RefreshCw, ShieldCheck, ShieldQuestion, Activity, XCircle } from "lucide-react";
import { listQueue } from "@/lib/offline-queue";

type Check = { name: string; status: string; detail: string; verification: string; category: string };
type Overview = {
  checked_at: string; health: Check[]; posture: Check[]; alerts: Array<{ severity: string; title: string; detail: string }>;
  rls: { status: string; verification: string; detail: string; tables: Array<{ table: string; rls_enabled: boolean }>; app_role_bypasses_rls?: boolean };
  configuration: Array<{ setting: string; status: string; verification: string }>;
  activity_24h: { by_action: Array<{ action: string; outcome: string; count: number }> };
  score: { score: number | null; points: number; out_of: number; factors: Array<{ name: string; passed: boolean; weight: number }>; not_counted: string[]; note: string };
};
type Event = { at: string; kind: string; action: string; outcome: string; actor: string; ip: string | null; method: string; path: string; resource_id: string | null; status_code: number };

const TABS = [["overview", "Overview"], ["auth", "Security events"], ["access", "Data access"], ["health", "System health"], ["config", "Configuration"]] as const;
const TONE: Record<string, string> = {
  Healthy: "text-good bg-good/10", Enabled: "text-good bg-good/10", Configured: "text-good bg-good/10", On: "text-good bg-good/10",
  Degraded: "text-warn bg-warn/10", "Partially enabled": "text-warn bg-warn/10", "Not configured": "text-warn bg-warn/10", Off: "text-ink-soft bg-base-deep",
  Unavailable: "text-bad bg-bad/10", Disabled: "text-bad bg-bad/10", "Unable to verify": "text-ink-soft bg-base-deep",
};
const Badge = ({ s }: { s: string }) => <span className={`inline-flex px-2 py-0.5 rounded-md text-xs font-semibold whitespace-nowrap ${TONE[s] || TONE[s.split(" (")[0]] || "text-ink-soft bg-base-deep"}`}>{s}</span>;
const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

export default function SecurityCenter() {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("overview");
  const [o, setO] = useState<Overview | null>(null);
  const [events, setEvents] = useState<Event[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("");
  const [device, setDevice] = useState<{ queued: number; lastSync: string | null; online: boolean }>({ queued: 0, lastSync: null, online: true });

  const load = () => {
    setError(null); setO(null);
    fetch("/api/v1/security/overview", { cache: "no-store" }).then(async (r) => {
      if (r.status === 401 || r.status === 403) throw new Error("You don't have permission to view the Security & Compliance Center.");
      if (!r.ok) throw new Error("Couldn't run the security checks. Please retry.");
      setO(await r.json());
    }).catch((e) => setError(e.message));
    listQueue().then((q) => setDevice({ queued: q.length, lastSync: localStorage.getItem("gstdesk-last-sync"), online: navigator.onLine })).catch(() => undefined);
  };
  useEffect(load, []);
  useEffect(() => {
    if (tab !== "auth" && tab !== "access") return;
    setEvents(null);
    fetch(`/api/v1/security/events?kind=${tab}${outcome ? `&outcome=${outcome}` : ""}&days=30`, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Couldn't load events")))).then(setEvents).catch((e) => setError(e.message));
  }, [tab, outcome]);

  const count = (pred: (a: string, out: string) => boolean) => (o?.activity_24h.by_action || []).filter((x) => pred(x.action, x.outcome)).reduce((s, x) => s + x.count, 0);
  const apiH = o?.health.filter((h) => h.status !== "Unable to verify" && h.status !== "Not configured") || [];
  const cards = o ? [
    { icon: ShieldCheck, label: "Security health score", value: o.score.score === null ? "—" : `${o.score.score}/100`, sub: `${o.score.points} of ${o.score.out_of} points from verified checks` },
    { icon: Activity, label: "API & system health", value: `${apiH.filter((h) => h.status === "Healthy").length}/${apiH.length} healthy`, sub: [apiH.filter((h) => h.status !== "Healthy").map((h) => `Problem: ${h.name}`).join(", "),
      o.health.filter((h) => !apiH.includes(h)).map((h) => h.name).join(", ") && `Not checked: ${o.health.filter((h) => !apiH.includes(h)).map((h) => `${h.name} (${h.status.toLowerCase()})`).join(", ")}`]
      .filter(Boolean).join(" · ") || "All checks passed" },
    { icon: KeyRound, label: "Authentication (24 h)", value: `${count((a) => a === "auth.failed")} denied`, sub: `${count((a) => a === "auth.success")} successful API-key sign-ins · user login: not configured` },
    { icon: Database, label: "Data access (24 h)", value: String(count((a) => !a.startsWith("auth."))), sub: "views, uploads, changes, downloads, reports" },
    { icon: CloudOff, label: "Backup & sync", value: "Backup: not configured", sub: device.lastSync ? `This device last synced ${when(device.lastSync)}` : `This device: ${device.queued} waiting, no sync yet` },
    { icon: ShieldQuestion, label: "Row-level security", value: o.rls.status, sub: o.rls.verification },
  ] : [];

  return (
    <div className="max-w-6xl">
      <header className="pt-8 pb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight">Security &amp; Compliance</h1>
          <p className="text-ink-soft mt-1">Every value below comes from a live check. Anything the app can&apos;t check is shown as &ldquo;Unable to verify&rdquo;.</p>
        </div>
        <button className="btn" onClick={load}><RefreshCw className="w-4 h-4" aria-hidden />Re-run checks</button>
      </header>

      <div className="flex gap-2 overflow-x-auto pb-2 mb-5" role="tablist">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
          className={`shrink-0 px-4 py-2 rounded-xl text-sm ${tab === k ? "bg-base shadow-neu-in text-ink-strong" : "bg-base shadow-neu-sm text-ink-soft"}`}>{l}</button>)}
      </div>

      {error && <div role="alert" className="neu-card p-5 text-bad mb-5">{error} <button className="underline ml-2" onClick={load}>Retry</button></div>}
      {!o && !error && <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 animate-pulse">{[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-28 neu-card" />)}</div>}

      {o && tab === "overview" && <>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {cards.map((c) => <div key={c.label} className="neu-card p-5"><c.icon className="w-5 h-5 text-accent-soft" aria-hidden />
            <div className="text-xl font-extrabold mt-3">{c.value}</div><div className="text-sm font-semibold">{c.label}</div><div className="text-xs text-ink-soft mt-1">{c.sub}</div></div>)}
        </div>
        <section className="neu-card p-5 mt-6">
          <h2 className="font-bold">Alerts</h2>
          {o.alerts.length === 0 ? <p className="text-sm text-ink-soft mt-2">No security alerts detected.</p> : (
            <ul className="mt-3 space-y-2">{o.alerts.map((a, i) => <li key={i} className="neu-inset p-3 flex gap-3 text-sm">
              <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${a.severity === "High" ? "text-bad" : "text-warn"}`} aria-hidden />
              <div><b>{a.title}</b> <span className="text-xs text-ink-faint">({a.severity})</span><div className="text-ink-soft">{a.detail}</div></div></li>)}</ul>)}
        </section>
        <section className="neu-card p-5 mt-6">
          <h2 className="font-bold">How the score is calculated</h2>
          <ul className="mt-3 grid sm:grid-cols-2 gap-2 text-sm">{o.score.factors.map((f) => <li key={f.name} className="flex items-center gap-2">
            {f.passed ? <CheckCircle2 className="w-4 h-4 text-good" aria-label="passed" /> : <XCircle className="w-4 h-4 text-bad" aria-label="failed" />}{f.name} <span className="text-ink-faint text-xs">({f.weight} pt)</span></li>)}</ul>
          {o.score.not_counted.length > 0 && <p className="text-xs text-ink-soft mt-3"><CircleHelp className="inline w-3.5 h-3.5" aria-hidden /> Not counted (couldn&apos;t be verified): {o.score.not_counted.join(", ")}.</p>}
          <p className="text-xs text-ink-faint mt-2">{o.score.note} Checked {when(o.checked_at)}.</p>
        </section>
      </>}

      {(tab === "auth" || tab === "access") && (
        <section className="neu-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
            <h2 className="font-bold">{tab === "auth" ? "Authentication events" : "Data access trail"} <span className="text-xs text-ink-faint font-normal">(last 30 days)</span></h2>
            <select className="field max-w-[180px]" value={outcome} onChange={(e) => setOutcome(e.target.value)} aria-label="Filter by outcome">
              <option value="">All outcomes</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option></select>
          </div>
          {tab === "auth" && <p className="text-xs text-ink-soft mb-3">GST Desk has no user login yet, so these are API-access attempts (API key accepted or requests denied). Login, logout and session events will appear once user accounts exist.</p>}
          {!events ? <div className="h-32 neu-inset animate-pulse" /> : events.length === 0 ? <p className="text-sm text-ink-soft py-6 text-center">No events recorded yet.</p> : (
            <div className="overflow-x-auto -mx-3"><table className="tbl">
              <thead><tr><th>When</th><th>Who</th><th>What</th><th>Status</th><th>From</th><th>Request</th></tr></thead>
              <tbody>{events.map((e, i) => <tr key={i}><td className="whitespace-nowrap text-ink-soft">{when(e.at)}</td><td>{e.actor}</td>
                <td className="font-semibold">{e.action.replace(".", " · ")}</td><td><Badge s={e.outcome === "success" ? "Healthy" : e.outcome === "denied" ? "Unavailable" : "Degraded"} /> <span className="text-xs text-ink-faint">{e.outcome} ({e.status_code})</span></td>
                <td className="text-ink-soft">{e.ip || "—"}</td><td className="text-xs text-ink-faint">{e.method} {e.path}</td></tr>)}</tbody>
            </table></div>)}
          <p className="text-[11px] text-ink-faint mt-3">IP addresses are partly masked. Keys, tokens and request contents are never stored.</p>
        </section>)}

      {o && tab === "health" && (
        <section className="neu-card p-5"><h2 className="font-bold mb-3">System health</h2>
          <div className="overflow-x-auto -mx-3"><table className="tbl"><thead><tr><th>Component</th><th>Status</th><th>Details</th><th>Verification</th></tr></thead>
            <tbody>{o.health.map((h) => <tr key={h.name}><td className="font-semibold">{h.name}</td><td><Badge s={h.status} /></td><td className="text-sm text-ink-soft">{h.detail}</td><td className="text-xs text-ink-faint">{h.verification}</td></tr>)}</tbody></table></div>
          <h3 className="font-semibold mt-6">This device</h3>
          <p className="text-sm text-ink-soft mt-1">{device.online ? "Online" : "Offline"} · {device.queued} invoice(s) waiting to upload · {device.lastSync ? `last sync ${when(device.lastSync)}` : "no sync recorded yet"}</p>
        </section>)}

      {o && tab === "config" && <>
        <section className="neu-card p-5"><h2 className="font-bold mb-3">Settings &amp; keys</h2>
          <p className="text-xs text-ink-soft mb-3">Only whether each setting is present is shown — never its value.</p>
          <div className="overflow-x-auto -mx-3"><table className="tbl"><thead><tr><th>Setting</th><th>Status</th></tr></thead>
            <tbody>{o.configuration.map((c) => <tr key={c.setting}><td>{c.setting}</td><td><Badge s={c.status} /></td></tr>)}</tbody></table></div></section>
        <section className="neu-card p-5 mt-6"><h2 className="font-bold mb-3">Security posture</h2>
          <ul className="space-y-2">{o.posture.map((p) => <li key={p.name} className="neu-inset p-3 text-sm flex flex-wrap gap-3 items-start">
            <Badge s={p.status} /><div className="flex-1 min-w-[200px]"><b>{p.name}</b><div className="text-ink-soft">{p.detail}</div></div><span className="text-xs text-ink-faint">{p.verification}</span></li>)}</ul></section>
        <section className="neu-card p-5 mt-6"><h2 className="font-bold">Row-level security (RLS)</h2>
          <p className="text-sm mt-2"><Badge s={o.rls.status} /> <span className="text-ink-soft">{o.rls.detail}</span></p>
          {o.rls.tables.length > 0 && <div className="flex flex-wrap gap-2 mt-3">{o.rls.tables.map((t) => <span key={t.table} className={`text-xs px-2 py-1 rounded-md ${t.rls_enabled ? "bg-good/10 text-good" : "bg-bad/10 text-bad"}`}>{t.table}</span>)}</div>}
        </section>
        <p className="text-xs text-ink-faint mt-4">GST Desk does not claim SOC 2, ISO 27001, GDPR, PCI DSS or any other certification.</p>
      </>}
    </div>
  );
}
