"use client";

import { useRef, useState } from "react";
import { Loader2, ScanLine } from "lucide-react";
import { api, type EinvResult } from "@/lib/api";
import { EinvBadge, SeverityDot } from "@/components/badges";
import { ErrorNote } from "@/components/ui";

const FIELDS: Array<[string, string]> = [["SellerGstin", "Seller GSTIN"], ["BuyerGstin", "Buyer GSTIN"], ["DocNo", "Invoice number"],
  ["DocDt", "Invoice date"], ["TotInvVal", "Invoice total"], ["ItemCnt", "Items"], ["MainHsnCode", "Main HSN"], ["IrnDt", "IRN date"]];

export function QrVerifier() {
  const input = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<EinvResult | null>(null);

  async function go(p: Promise<EinvResult>) {
    setBusy(true);
    setError(null);
    setRes(null);
    try {
      setRes(await p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Verification failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <label className="block">
        <span className="text-sm text-ink-soft">Paste the text from a scanned QR code</span>
        <textarea value={text} onChange={(e) => { setText(e.target.value); setError(null); }} rows={3} className="field mt-1.5 font-mono text-xs"
          placeholder="eyJhbGciOiJSUzI1NiIs…" />
      </label>
      <div className="flex flex-wrap gap-3 mt-3">
        <button className="btn-primary" disabled={busy} onClick={() => {
          if (!text.trim()) { setError("Paste the QR text, or upload an image of the invoice instead."); return; }
          go(api.einvoiceVerify(text));
        }}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <ScanLine className="w-4 h-4" aria-hidden />} Verify text
        </button>
        <input ref={input} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" className="sr-only" aria-label="Invoice image or PDF"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) go(api.einvoiceVerifyFile(f)); e.target.value = ""; }} />
        <button className="btn" disabled={busy} onClick={() => input.current?.click()}>Scan an image or PDF</button>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}

      {res && (
        <div className="mt-5 neu-inset p-4 rise">
          <div className="flex items-center justify-between gap-3">
            <EinvBadge value={res.status} />
            {res.irn && <span className="text-[11px] text-ink-faint truncate">IRN {res.irn.slice(0, 20)}…</span>}
          </div>
          {res.data && (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 mt-4 text-sm">
              {FIELDS.map(([k, l]) => (
                <div key={k}><dt className="text-xs text-ink-faint">{l}</dt><dd className="truncate">{String(res.data?.[k] ?? "—")}</dd></div>
              ))}
            </dl>
          )}
          <ul className="mt-4 space-y-1.5">
            {res.findings.map((f) => (
              <li key={f.code} className="flex gap-2 text-sm"><span className="mt-1.5"><SeverityDot severity={f.severity} /></span>{f.message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
