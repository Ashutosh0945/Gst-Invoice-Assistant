"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

export function PaymentForm({ invoiceId, paidOn }: { invoiceId: string; paidOn: string | null }) {
  const router = useRouter();
  const [value, setValue] = useState(paidOn ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save(v: string | null) {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await api.recordPayment(invoiceId, v);
      setSaved(true);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the payment date.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (!value) { setError("Pick the date you paid the vendor."); return; } save(value); }}>
      <label className="block">
        <span className="text-sm text-ink-soft">Date you paid the vendor</span>
        <input type="date" value={value} onChange={(e) => { setValue(e.target.value); setError(null); setSaved(false); }}
          className="field mt-1.5" max={new Date().toISOString().slice(0, 10)} />
      </label>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex gap-3 mt-3">
        <button type="submit" disabled={busy} className="btn-primary flex-1">{busy ? "Saving…" : "Save payment date"}</button>
        {paidOn && <button type="button" disabled={busy} onClick={() => { setValue(""); save(null); }} className="btn">Clear</button>}
      </div>
      {saved && <p className="text-sm text-good mt-2">Saved. Credit re-checked.</p>}
    </form>
  );
}
