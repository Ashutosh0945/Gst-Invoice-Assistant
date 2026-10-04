"use client";

import { useEffect, useState } from "react";
import { CloudUpload, Download, WifiOff } from "lucide-react";
import { listQueue, onQueueChange, processQueue } from "@/lib/offline-queue";

declare global { interface Window { __gstInstall?: Event & { prompt: () => Promise<void> } } }

/** Registers the service worker, syncs the offline queue when back online, shows the
 *  online/offline state and the install button. Mounted once in the root layout. */
export function PwaManager() {
  const [online, setOnline] = useState(true);
  const [queued, setQueued] = useState(0);
  const [canInstall, setCanInstall] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch(() => undefined);
    const refresh = () => listQueue().then((q) => setQueued(q.length)).catch(() => undefined);
    const sync = async () => {
      const n = await processQueue((item, num) => notify(`Uploaded ${num || item.name}`, "Your offline invoice has been processed.")).catch(() => 0);
      if (n) setToast(`${n} queued invoice${n > 1 ? "s" : ""} uploaded`);
      refresh();
    };
    const on = () => { setOnline(true); sync(); }, off = () => setOnline(false);
    setOnline(navigator.onLine);
    window.addEventListener("online", on); window.addEventListener("offline", off);
    const offQ = onQueueChange(refresh);
    const timer = setInterval(() => { if (navigator.onLine) sync(); }, 60_000);
    const bip = (e: Event) => { e.preventDefault(); window.__gstInstall = e as Window["__gstInstall"]; setCanInstall(true); };
    window.addEventListener("beforeinstallprompt", bip);
    refresh(); if (navigator.onLine) sync();
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); offQ();
      clearInterval(timer); window.removeEventListener("beforeinstallprompt", bip); };
  }, []);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 4000); return () => clearTimeout(t); } }, [toast]);

  return (
    <>
      {!online && (
        <div role="status" className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl bg-warn text-white text-sm font-semibold shadow-glow flex items-center gap-2">
          <WifiOff className="w-4 h-4" aria-hidden />Offline — new invoices will be saved and uploaded later
        </div>
      )}
      {queued > 0 && online && (
        <a href="/settings#offline" className="fixed bottom-4 right-4 z-50 px-3.5 py-2 rounded-xl bg-accent text-white text-sm shadow-glow flex items-center gap-2">
          <CloudUpload className="w-4 h-4" aria-hidden />{queued} waiting to upload</a>
      )}
      {canInstall && (
        <button onClick={async () => { await window.__gstInstall?.prompt(); setCanInstall(false); }}
          className="fixed bottom-4 left-4 z-50 px-3.5 py-2 rounded-xl bg-base-raised shadow-neu text-sm flex items-center gap-2">
          <Download className="w-4 h-4 text-accent-soft" aria-hidden />Install app</button>
      )}
      {toast && <div role="status" className="fixed top-20 right-4 z-50 px-4 py-2.5 rounded-xl bg-good text-white text-sm shadow-glow">{toast}</div>}
    </>
  );
}

export function notify(title: string, body: string, url = "/invoices") {
  try {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    navigator.serviceWorker?.ready.then((reg) => reg.showNotification(title, { body, icon: "/icons/icon-192.png", data: { url } }))
      .catch(() => new Notification(title, { body }));
  } catch { /* notifications unsupported */ }
}
