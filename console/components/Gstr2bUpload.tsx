"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { FileJson, Loader2, Trash2 } from "lucide-react";
import { api, periodLabel } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

export function Gstr2bUpload() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload(f: File | undefined) {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".json")) {
      setError("Upload the JSON file from the GST portal (Returns → GSTR-2B → Download JSON).");
      return;
    }
    setBusy(true);
    setError(null);
    setMsg(null);
    try {
      const imp = await api.gstr2bImport(f);
      setMsg(`Imported ${imp.record_count} invoices for ${periodLabel(imp.return_period)}.`);
      router.push(`/gstr2b?import=${imp.id}`);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div>
      <input ref={input} type="file" accept=".json,application/json" className="sr-only" aria-label="GSTR-2B JSON file"
        onChange={(e) => upload(e.target.files?.[0])} />
      <button className="btn-primary" onClick={() => input.current?.click()} disabled={busy}>
        {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <FileJson className="w-4 h-4" aria-hidden />}
        {busy ? "Importing…" : "Import GSTR-2B"}
      </button>
      {msg && <p className="text-sm text-good mt-2">{msg}</p>}
      {error && <ErrorNote>{error}</ErrorNote>}
    </div>
  );
}

export function DeleteImport({ id, label }: { id: string; label: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!confirming) {
    return <button className="btn py-1.5 text-ink-soft" onClick={() => setConfirming(true)}><Trash2 className="w-4 h-4" aria-hidden />Remove</button>;
  }
  return (
    <span className="flex items-center gap-2 text-sm">
      Remove {label}?
      <button className="btn py-1.5 text-bad" disabled={busy} onClick={async () => {
        setBusy(true);
        await api.gstr2bDelete(id).catch(() => undefined);
        router.push("/gstr2b");
        router.refresh();
      }}>{busy ? "Removing…" : "Remove"}</button>
      <button className="btn py-1.5" onClick={() => setConfirming(false)}>Keep</button>
    </span>
  );
}
