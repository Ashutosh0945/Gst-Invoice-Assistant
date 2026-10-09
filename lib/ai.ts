// Browser-side client for the AI endpoints (/api/v1/ai/*). Requests go to this site's own
// /api, which runs on the server; the OpenRouter key never reaches the browser.

export interface Kpis {
  period: { key: string; label: string };
  total_invoices: number; total_purchase_value: number; gst_amount: number; itc_total: number;
  itc_eligible: number; itc_at_risk: number; itc_blocked: number; gstr2b_matched: number;
  gstr2b_mismatches: number; invoices_missing_in_2b: number; needs_review: number; gstr2b_imported: boolean;
}
export interface RiskItem {
  key: string; severity: "Critical" | "High" | "Review"; category: string; title: string; reason: string;
  invoice_id: string | null; invoice_number: string | null; vendor: string | null; amount_at_stake: number | null;
  next_action: string;
}
export interface Card {
  type: "kpis" | "table" | "link"; title: string; items?: Array<[string, string | number]>;
  columns?: string[]; rows?: Array<Array<string | number | null>>; row_links?: string[]; link?: string | null; href?: string;
}
export interface CopilotReply {
  answer: string; answer_source: "ai" | "rules"; note: string | null; intent: string;
  context: Record<string, unknown>; facts: Record<string, unknown>; cards: Card[]; followups: string[];
  evidence?: { period: string; data_sources: string[]; definition: string | null; records: Array<{ label: string; href: string }>;
    response_categories: string[]; provenance: string; limitations: string };
}
export interface Stage { stage: string; status: "pass" | "warn" | "fail" | "na"; summary: string; evidence: Array<Record<string, unknown>> }
export interface Investigation {
  invoice: { id: string; invoice_number: string | null; vendor: string | null; vendor_gstin: string | null;
    invoice_date: string | null; grand_total: number; gst: number; status: string };
  stages: Stage[]; verdict: "pass" | "warn" | "fail";
  explanation?: { text: string; source: "ai" | "rules"; note: string | null };
}
export interface Brief {
  generated_at: string;
  facts: { period: string; period_kpis: Record<string, number>; issue_counts: Record<string, number>;
    important_issues: Array<{ severity: string; title: string; invoice_number: string | null; vendor: string | null; amount_at_stake: number | null }>;
    vendors_needing_attention: Array<{ vendor_name: string; gst_errors: number; gstr2b_mismatches: number; itc_at_risk: number }>;
    trend: { previous_month: string; latest_month: string; purchase_change_pct: number; gst_change_pct: number | null } | null };
  commentary: { text: string; source: "ai" | "rules"; note: string | null };
}
export interface SearchResult {
  query: string; understood_as: string[]; understood_by: string; count: number; note: string | null;
  results: Array<{ invoice_id: string; invoice_number: string | null; vendor: string | null; invoice_date: string | null;
    grand_total: number; status: string; gstr2b_status: string | null }>;
}
export interface Anomaly { invoice_id: string; invoice_number: string | null; vendor: string | null; amount: number; kind: string; score: number; reason: string }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1/ai${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) }, cache: "no-store" });
  const text = await res.text();
  let data: unknown = null;
  try { data = JSON.parse(text); } catch { /* not JSON */ }
  if (!res.ok) {
    const d = (data as { detail?: unknown })?.detail;
    throw new Error(typeof d === "string" ? d : res.status >= 500 ? "The AI service hit an error. Please try again." : "Request failed.");
  }
  return data as T;
}

export const ai = {
  kpis: (period = "all") => call<Kpis>(`/kpis?period=${period}`),
  risks: () => call<{ items: RiskItem[]; counts: Record<string, number> }>("/risks"),
  anomalies: () => call<{ items: Anomaly[]; vendors_with_insufficient_history: number; note: string }>("/anomalies"),
  copilot: (message: string, history: Array<{ role: string; content: string }>, context: unknown) =>
    call<CopilotReply>("/copilot", { method: "POST", body: JSON.stringify({ message, history: history.slice(-10), context }) }),
  search: (query: string) => call<SearchResult>("/search", { method: "POST", body: JSON.stringify({ query }) }),
  investigate: (id: string, explain = false) => call<Investigation>(`/investigate/${id}${explain ? "?explain=true" : ""}`),
  brief: (period = "this_month") => call<Brief>(`/brief?period=${period}`, { method: "POST" }),
  monthly: () => call<Array<{ month: string; invoices: number; purchase_value: number; gst: number; itc_eligible: number }>>("/monthly"),
  report: (kind: "monthly" | "audit", period: string) => call<Report>(`/reports/${kind}?period=${period}`, { method: "POST" }),
  forecast: (months = 3) => call<Forecast>(`/forecast?months=${months}`),
  whatif: (body: { scenario: string; pct?: number; invoice_id?: string }) => call<WhatIf>("/whatif", { method: "POST", body: JSON.stringify(body) }),
  vendorProfile: (key: string, explain = false) => call<VendorProfile>(`/vendors/${encodeURIComponent(key)}/profile${explain ? "?explain=true" : ""}`),
  vendorsList: () => call<Array<{ vendor_key: string; vendor_name: string; invoice_count: number; attention_score: number }>>("/vendors"),
  recon2b: (id: string) => call<Recon2b>(`/reconcile/gstr2b/${id}`),
  reconPo: (id: string) => call<{ po_number: string | null; lines: Array<Record<string, unknown>>; explanation: Expl }>(`/reconcile/po/${id}`),
  vendorMessage: (invoice_id: string, issue?: string) => call<VendorMsg>("/vendor-message", { method: "POST", body: JSON.stringify({ invoice_id, issue }) }),
  feedback: () => call<Feedback>("/feedback/metrics"),
  suggestions: () => call<{ suggestions: string[] }>("/suggestions"),
};

export const inr = (v: number | string | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;

/** Compact Indian format for small cards: ₹24.92 L, ₹1.2 Cr (exact value goes in a tooltip). */
export const inrShort = (v: number | null | undefined) => {
  const n = Number(v ?? 0);
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return inr(n);
};

export type Expl = { text: string; source: "ai" | "rules"; note: string | null };
export interface Report {
  kind: "monthly" | "audit"; generated_at: string; summary?: Expl; executive_summary?: Expl; sections?: string[];
  facts: { period: { label: string }; processing: { invoices: number; status_counts: Record<string, number>; average_confidence_pct: number | null };
    gst: { purchase_value: number; gst_amount: number; by_rate: Array<{ rate: string; taxable: number; gst: number; lines: number }> };
    itc: Record<string, number>; gstr2b: { imported: boolean; records: number; by_status: Record<string, number>; missing_in_2b: number };
    validation: { error_findings: number; by_code: Record<string, number> };
    vendors: Array<{ vendor_name: string; invoice_count: number; purchase_value: number; gst_errors: number; gstr2b_mismatches: number; itc_at_risk: number }>;
    anomalies: Anomaly[]; review_items: Array<{ severity: string; category: string; title: string; invoice_number: string | null; invoice_id: string | null; vendor: string | null; amount_at_stake: number | null }>;
    trend: Array<{ month: string; invoices: number; purchase_value: number; gst: number }>;
    detailed_findings: Array<{ invoice_id: string; invoice_number: string | null; vendor: string | null; code: string; category: string; message: string }> };
}
export interface Forecast {
  status: "ok" | "insufficient_history"; label: string; what: string; method: string; message: string; confidence?: string;
  history: Array<{ month: string; gst: number; itc_eligible: number }>; forecast: Array<{ month: string; estimate: number; low: number; high: number }>;
}
export interface WhatIf { scenario: string; note: string; assumption: string; status?: { current: string; simulated: string };
  simulated_reasons?: string[]; rows: Array<{ metric: string; current: number; simulated: number; change: number }> }
export interface VendorProfile {
  profile: { vendor_name: string; vendor_gstin: string | null; invoice_count: number; purchase_value: number; average_invoice_value: number;
    gst_errors: number; gstr2b_mismatches: number; filing_rate_pct: number | null; itc_at_risk: number; einvoice_problems: number;
    repeated_issues: Array<{ code: string; times: number }> };
  monthly_trend: Array<{ month: string; invoices: number; value: number; errors: number }>;
  invoices: Array<{ invoice_id: string; invoice_number: string | null; invoice_date: string | null; grand_total: number; status: string; gstr2b_status: string | null; errors: string[] }>;
  summary?: Expl;
}
export interface Recon2b { record: { id: string; supplier_name: string | null; supplier_gstin: string; invoice_number: string; match_status: string; matched_invoice_id: string | null };
  comparison: Array<{ field: string; your_books: string | number | null; gstr2b: string | number | null; match: boolean }>; reason: string; explanation: Expl }
export interface VendorMsg { subject: string; body: string; source: string; note: string | null; reminder: string; facts: Record<string, unknown> }
export interface Feedback { total_feedback: number; minimum_for_metrics: number; enough_data: boolean; message: string | null; policy: string;
  fields: Array<{ field: string; reviewed: number; corrected: number; accuracy_pct: number }>; trend: Array<{ month: string; reviewed: number; accuracy_pct: number }> }
