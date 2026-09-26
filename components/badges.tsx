type Tone = "good" | "warn" | "bad" | "info" | "accent" | "muted";
const TONES: Record<Tone, string> = {
  good: "text-good bg-good/10", warn: "text-warn bg-warn/10", bad: "text-bad bg-bad/10",
  info: "text-info bg-info/10", accent: "text-accent-soft bg-accent/15", muted: "text-ink-soft bg-white/5",
};

export function Badge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold whitespace-nowrap ${TONES[tone]}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" aria-hidden />{children}
    </span>
  );
}

function make(map: Record<string, [Tone, string]>) {
  return function Mapped({ value }: { value: string | null | undefined }) {
    if (!value) return <Badge tone="muted">Not checked</Badge>;
    const [tone, label] = map[value] ?? ["muted", value.replaceAll("_", " ").toLowerCase()];
    return <Badge tone={tone}>{label}</Badge>;
  };
}

export const StatusBadge = make({
  AUTO_APPROVED: ["good", "Auto-approved"], APPROVED: ["good", "Approved"], NEEDS_REVIEW: ["warn", "Needs review"],
  REJECTED: ["bad", "Rejected"], FAILED: ["bad", "Failed"], PROCESSING: ["muted", "Processing"],
});

export const ItcBadge = make({
  ELIGIBLE: ["good", "Eligible"], PARTIALLY_ELIGIBLE: ["info", "Partly eligible"], AWAITING_2B: ["accent", "Awaiting GSTR-2B"],
  NEEDS_REVIEW: ["warn", "Needs review"], NOT_IN_2B: ["bad", "Not in 2B"], REVERSAL_DUE: ["bad", "Reversal due"],
  BLOCKED: ["muted", "Blocked"], LAPSED: ["bad", "Lapsed"], NOT_APPLICABLE: ["muted", "Not applicable"],
});

export const TwoBBadge = make({ IN_2B: ["good", "In 2B"], MISSING_IN_2B: ["bad", "Missing in 2B"] });

export const MatchBadge = make({
  MATCHED: ["good", "Matched"], FUZZY_MATCHED: ["info", "Number differs"], DATE_MISMATCH: ["info", "Date differs"],
  AMOUNT_MISMATCH: ["warn", "Amount differs"], MISSING_IN_BOOKS: ["bad", "Not in your books"],
});

export const EinvBadge = make({
  VERIFIED: ["good", "Verified"], UNVERIFIED: ["accent", "Signature not checked"], MISMATCH: ["bad", "Doesn't match QR"],
  SIGNATURE_INVALID: ["bad", "Forged signature"], MALFORMED: ["warn", "Unreadable QR"], NO_QR: ["muted", "No QR"],
});

export const RiskBadge = make({ Low: ["good", "Low"], Medium: ["warn", "Medium"], High: ["bad", "High"] });

export function SeverityDot({ severity }: { severity: string }) {
  const c = severity === "ERROR" ? "bg-bad" : severity === "WARNING" ? "bg-warn" : "bg-ink-faint";
  return <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${c}`} aria-label={severity.toLowerCase()} />;
}
