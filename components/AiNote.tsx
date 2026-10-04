import { ShieldCheck } from "lucide-react";
import type { Expl } from "@/lib/ai";

/** Shows AI-written text clearly separated from calculated facts. */
export function AiNote({ e, title = "Summary" }: { e?: Expl | null; title?: string }) {
  if (!e) return null;
  return (
    <div className="rounded-2xl bg-accent/10 p-4">
      <div className="label mb-1.5 flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5 text-good" aria-hidden />
        {title.toUpperCase()} · {e.source === "ai" ? "AI COMMENTARY, NUMBERS VERIFIED" : "RULE-BASED"}</div>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{e.text}</p>
      {e.note && <p className="text-[11px] text-ink-faint mt-1.5">{e.note}</p>}
    </div>
  );
}
