"use client";

import { useEffect, useState } from "react";
import { Bell, Brain, CloudUpload, Download, Palette, RefreshCw, Trash2 } from "lucide-react";
import { ai, type Feedback } from "@/lib/ai";
import { listQueue, onQueueChange, processQueue, removeItem, retryNow, type QueueItem } from "@/lib/offline-queue";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function Settings() {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [perm, setPerm] = useState<string>("default");
  const [fb, setFb] = useState<Feedback | null>(null);
  const [installed, setInstalled] = useState(false);
  useEffect(() => {
    const load = () => listQueue().then(setQueue).catch(() => undefined);
    load(); const off = onQueueChange(load);
    setPerm("Notification" in window ? Notification.permission : "unsupported");
    setInstalled(window.matchMedia("(display-mode: standalone)").matches);
    ai.feedback().then(setFb).catch(() => undefined);
    return off;
  }, []);

  return (
    <div className="max-w-3xl">
      <h1 className="text-[28px] md:text-[32px] font-extrabold tracking-tight pt-8 pb-6">Settings</h1>
      <section className="neu-card p-5"><h2 className="font-bold flex items-center gap-2"><Palette className="w-5 h-5 text-accent-soft" aria-hidden />Appearance</h2>
        <div className="flex items-center justify-between mt-3"><p className="text-sm text-ink-soft">Light, dark, or follow your device (System).</p><div className="[&>div]:flex"><ThemeToggle /></div></div></section>

      <section className="neu-card p-5 mt-6"><h2 className="font-bold flex items-center gap-2"><Download className="w-5 h-5 text-accent-soft" aria-hidden />App &amp; notifications</h2>
        <p className="text-sm text-ink-soft mt-2">{installed ? "GST Desk is installed on this device." : "Install GST Desk from your browser menu (“Install app” / “Add to Home Screen”) to use it like an app and add invoices offline."}</p>
        <div className="flex items-center justify-between mt-4"><p className="text-sm">Notifications when offline invoices finish uploading: <b>{perm === "unsupported" ? "not supported in this browser" : perm}</b></p>
          {perm === "default" && <button className="btn" onClick={async () => setPerm(await Notification.requestPermission())}><Bell className="w-4 h-4" aria-hidden />Allow</button>}</div>
        <p className="text-xs text-ink-faint mt-2">Notifications are shown by this device when it syncs. Server push to a closed app isn&apos;t set up (it needs a push service and keys).</p></section>

      <section id="offline" className="neu-card p-5 mt-6"><div className="flex justify-between items-center"><h2 className="font-bold flex items-center gap-2"><CloudUpload className="w-5 h-5 text-accent-soft" aria-hidden />Offline queue</h2>
        {queue.length > 0 && <button className="btn py-1.5" onClick={() => processQueue()}><RefreshCw className="w-4 h-4" aria-hidden />Sync now</button>}</div>
        {queue.length === 0 ? <p className="text-sm text-ink-soft mt-2">Nothing waiting. Invoices added while offline appear here and upload automatically.</p> : (
          <ul className="mt-3 space-y-2">{queue.map((q) => <li key={q.hash} className="neu-inset p-3 flex flex-wrap items-center gap-3 text-sm">
            <span className="font-semibold flex-1 min-w-[160px] truncate">{q.name}</span>
            <span className={q.status === "failed" ? "text-bad" : "text-ink-soft"}>{q.status}{q.attempts ? ` · ${q.attempts} attempt${q.attempts > 1 ? "s" : ""}` : ""}</span>
            {q.lastError && <span className="text-xs text-ink-faint w-full">{q.lastError}</span>}
            <button className="btn py-1" onClick={() => retryNow(q.hash)}>Retry</button>
            <button className="btn py-1" aria-label={`Remove ${q.name}`} onClick={() => removeItem(q.hash)}><Trash2 className="w-4 h-4" /></button></li>)}</ul>)}</section>

      <section className="neu-card p-5 mt-6"><h2 className="font-bold flex items-center gap-2"><Brain className="w-5 h-5 text-accent-soft" aria-hidden />Learning from corrections</h2>
        {!fb ? <p className="text-sm text-ink-soft mt-2">Loading…</p> : <>
          <p className="text-sm mt-2">{fb.total_feedback} field corrections recorded from reviewers.</p>
          {fb.enough_data ? <div className="overflow-x-auto -mx-3 mt-3"><table className="tbl"><thead><tr><th>Field</th><th className="num">Reviewed</th><th className="num">Corrected</th><th className="num">Read correctly</th></tr></thead>
            <tbody>{fb.fields.map((f) => <tr key={f.field}><td>{f.field}</td><td className="num">{f.reviewed}</td><td className="num">{f.corrected}</td><td className="num font-semibold">{f.accuracy_pct}%</td></tr>)}</tbody></table></div>
            : <p className="text-sm text-ink-soft mt-1">{fb.message}</p>}
          <p className="text-xs text-ink-faint mt-3">{fb.policy}</p>
          <a className="btn mt-3" href="/api/v1/ai/feedback/export"><Download className="w-4 h-4" aria-hidden />Download dataset (JSONL)</a></>}</section>
    </div>
  );
}
