"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import { app, inr } from "@/lib/client";
import { useMe } from "@/components/AppShell";
import { Card, ErrorNote } from "@/components/ui";

type Line = { description: string; hsn_sac: string; quantity: string; rate: string; gst_rate: string };
const blank = (): Line => ({ description: "", hsn_sac: "", quantity: "1", rate: "", gst_rate: "18" });

export default function NewInvoice() {
  const { me } = useMe();
  const router = useRouter();
  const [states, setStates] = useState<Array<{ code: string; name: string }>>([]);
  const [client, setClient] = useState({ client_name: "", client_email: "", client_gstin: "", place_of_supply: me.state_code ?? "27", due_in_days: "15", notes: "" });
  const [lines, setLines] = useState<Line[]>([blank()]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { app.states().then(setStates).catch(() => undefined); }, []);

  const registered = !!me.gstin;
  const preview = useMemo(() => {
    let sub = 0, tax = 0;
    for (const l of lines) {
      const t = (Number(l.quantity) || 0) * (Number(l.rate) || 0);
      sub += t;
      if (registered) tax += (t * (Number(l.gst_rate) || 0)) / 100;
    }
    return { sub, tax, total: sub + tax, inter: client.place_of_supply !== me.state_code };
  }, [lines, registered, client.place_of_supply, me.state_code]);

  const setLine = (i: number, k: keyof Line, v: string) => { setLines((ls) => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l))); setError(null); };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!client.client_name.trim()) return setError("Enter who the invoice is for.");
    const items = lines.filter((l) => l.description.trim() || l.rate);
    if (!items.length) return setError("Add at least one item with a price.");
    if (items.some((l) => !l.description.trim() || !(Number(l.rate) >= 0) || l.rate === "")) return setError("Every item needs a description and a price.");
    setBusy(true);
    try {
      await app.createInvoice({
        client_name: client.client_name, client_email: client.client_email || null, client_gstin: client.client_gstin || null,
        place_of_supply: client.place_of_supply, due_in_days: Number(client.due_in_days) || 0, notes: client.notes || null,
        items: items.map((l) => ({ description: l.description, hsn_sac: l.hsn_sac || null, quantity: Number(l.quantity) || 1,
          rate: Number(l.rate), gst_rate: Number(l.gst_rate) || 0 })),
      });
      router.push("/app/invoices");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't create the invoice.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate>
      <Link href="/app/invoices" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-white mt-6"><ArrowLeft className="w-4 h-4" aria-hidden /> Invoices</Link>
      <h1 className="text-[28px] font-extrabold tracking-tight pt-4 pb-6">New invoice</h1>
      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6 min-w-0">
          <Card title="Bill to">
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="block"><span className="text-sm text-ink-soft">Client name</span>
                <input className="field mt-1.5" value={client.client_name} onChange={(e) => setClient({ ...client, client_name: e.target.value })} /></label>
              <label className="block"><span className="text-sm text-ink-soft">Client email (optional)</span>
                <input className="field mt-1.5" type="email" value={client.client_email} onChange={(e) => setClient({ ...client, client_email: e.target.value })} /></label>
              <label className="block"><span className="text-sm text-ink-soft">Client GSTIN (optional)</span>
                <input className="field mt-1.5 uppercase" maxLength={15} value={client.client_gstin} onChange={(e) => setClient({ ...client, client_gstin: e.target.value })} /></label>
              <label className="block"><span className="text-sm text-ink-soft">Client&apos;s state</span>
                <select className="field mt-1.5" value={client.place_of_supply} onChange={(e) => setClient({ ...client, place_of_supply: e.target.value })}>
                  {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                </select></label>
            </div>
          </Card>
          <Card title="Items" action={<button type="button" className="btn py-1.5" onClick={() => setLines([...lines, blank()])}><Plus className="w-4 h-4" aria-hidden />Add item</button>}>
            <div className="space-y-4">
              {lines.map((l, i) => (
                <div key={i} className="neu-inset p-4 grid grid-cols-2 md:grid-cols-[2fr_1fr_0.7fr_1fr_0.8fr_auto] gap-3 items-end">
                  <label className="col-span-2 md:col-span-1"><span className="text-xs text-ink-soft">Description</span>
                    <input className="field mt-1" value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} placeholder="e.g. Website design" /></label>
                  <label><span className="text-xs text-ink-soft">HSN/SAC</span><input className="field mt-1" value={l.hsn_sac} onChange={(e) => setLine(i, "hsn_sac", e.target.value)} placeholder="998314" /></label>
                  <label><span className="text-xs text-ink-soft">Qty</span><input className="field mt-1" inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, "quantity", e.target.value)} /></label>
                  <label><span className="text-xs text-ink-soft">Price (₹)</span><input className="field mt-1" inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, "rate", e.target.value)} /></label>
                  <label><span className="text-xs text-ink-soft">GST %</span>
                    <select className="field mt-1" value={l.gst_rate} disabled={!registered} onChange={(e) => setLine(i, "gst_rate", e.target.value)}>
                      {["0", "5", "18", "40"].map((r) => <option key={r} value={r}>{r}%</option>)}
                    </select></label>
                  <button type="button" className="btn px-2.5 py-2.5" aria-label="Remove item" disabled={lines.length === 1} onClick={() => setLines(lines.filter((_, j) => j !== i))}><Trash2 className="w-4 h-4" /></button>
                </div>
              ))}
            </div>
            {!registered && <p className="text-xs text-ink-faint mt-3">You haven&apos;t added a GSTIN, so no GST is charged. Add it in Settings if you&apos;re registered.</p>}
          </Card>
        </div>
        <div className="xl:sticky xl:top-8 self-start">
          <Card title="Summary">
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-ink-soft">Before tax</dt><dd className="tabular">{inr(preview.sub, true)}</dd></div>
              {registered && <div className="flex justify-between"><dt className="text-ink-soft">{preview.inter ? "IGST" : "CGST + SGST"}</dt><dd className="tabular">{inr(preview.tax, true)}</dd></div>}
              <div className="flex justify-between text-lg font-extrabold pt-2 border-t border-base-line"><dt>Total</dt><dd className="tabular">{inr(preview.total, true)}</dd></div>
            </dl>
            <label className="block mt-5"><span className="text-sm text-ink-soft">Payment due in</span>
              <select className="field mt-1.5" value={client.due_in_days} onChange={(e) => setClient({ ...client, due_in_days: e.target.value })}>
                {["0", "7", "15", "30", "45", "60"].map((d) => <option key={d} value={d}>{d === "0" ? "Due on receipt" : `${d} days`}</option>)}
              </select></label>
            <label className="block mt-4"><span className="text-sm text-ink-soft">Note on invoice</span>
              <textarea className="field mt-1.5" rows={2} value={client.notes} onChange={(e) => setClient({ ...client, notes: e.target.value })} placeholder="Bank details, thank-you note…" /></label>
            {error && <ErrorNote>{error}</ErrorNote>}
            <button className="btn-primary w-full mt-5 py-3" disabled={busy}>{busy ? "Creating…" : "Create invoice"}</button>
          </Card>
        </div>
      </div>
    </form>
  );
}
