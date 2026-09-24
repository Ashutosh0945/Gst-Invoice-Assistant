"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Check, X } from "lucide-react";
import { api } from "@/lib/api";
import { ErrorNote } from "@/components/ui";

export function ReviewActions({ invoiceId }: { invoiceId: string }) {
  const router = useRouter();
  const [reviewer, setReviewer] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "approve" | "reject") {
    if (!reviewer.trim()) {
      setError("Enter your name before recording a decision.");
      return;
    }
    setError(null);
    setBusy(action);
    try {
      await (action === "approve" ? api.approve : api.reject)(invoiceId, reviewer.trim(), notes.trim() || undefined);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The request failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-sm text-ink-soft">Your name</span>
        <input value={reviewer} onChange={(e) => { setReviewer(e.target.value); setError(null); }}
          className="field mt-1.5" placeholder="e.g. Priya" />
      </label>
      <label className="block">
        <span className="text-sm text-ink-soft">Note (optional)</span>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="field mt-1.5"
          placeholder="Why you approved or rejected it" />
      </label>
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex gap-3 pt-1">
        <button onClick={() => act("approve")} disabled={busy !== null} className="btn-primary flex-1">
          <Check className="w-4 h-4" aria-hidden />{busy === "approve" ? "Approving…" : "Approve"}
        </button>
        <button onClick={() => act("reject")} disabled={busy !== null} className="btn flex-1 text-bad">
          <X className="w-4 h-4" aria-hidden />{busy === "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </div>
  );
}
