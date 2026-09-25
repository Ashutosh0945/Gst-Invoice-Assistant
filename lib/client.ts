// Browser-side API client for the personal app. The session is an HttpOnly cookie
// set by the API, so requests only need `credentials: "include"`.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(`/api/v1/app${path}`, {
    ...init,
    credentials: "include",
    headers: isForm ? init.headers : { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const detail = (data as { detail?: unknown })?.detail;
    const msg = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d) => (d as { msg?: string }).msg).filter(Boolean).join(". ")
      : res.status === 401 ? "Please sign in."
      : res.status === 413 ? "That file is too large. Use a file under 4 MB."
      : res.status === 504 ? "The server took too long. Try again in a minute."
      : res.status >= 500 ? "Our server couldn't be reached or hit an error. Please try again shortly."
      : "Something went wrong. Try again.";
    if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/auth")) {
      window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
    }
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

const json = (body: unknown) => JSON.stringify(body);

export type Profile = "individual" | "business" | "freelancer";
export interface Me {
  id: string; name: string; email: string; profile_type: Profile; business_name: string | null;
  gstin: string | null; state_code: string | null; state_name: string | null; has_tax_profile: boolean;
}
export interface BillRow {
  id: string; vendor: string | null; invoice_number: string | null; date: string | null; total: string | null;
  category: string; category_label: string; warranty_until: string | null; einvoice_status: string | null;
  added: string; file: string;
}
export interface BillDetail extends BillRow {
  note: string | null; vendor_gstin: string | null; subtotal: string | null; cgst: string | null; sgst: string | null;
  igst: string | null; categories: Record<string, string>;
  items: Array<{ line_no: number; description: string | null; hsn_sac: string | null; quantity: string | null;
    rate: string | null; gst_rate: string | null; amount: string | null }>;
  insights: { headline: string; tone: "good" | "warn" | "bad"; problems: string[]; tips: string[];
    overcharges: Array<{ description: string; charged_rate: string; expected_rate: string; extra: string }>;
    overcharge_total: string; gst_paid: string; gst_claimable: string | null };
}
export interface SalesInvoice {
  id: string; number: string; client_name: string; client_email: string | null; client_gstin: string | null;
  issue_date: string; due_date: string | null; total: string; subtotal: string; cgst: string; sgst: string; igst: string;
  status: "DRAFT" | "SENT" | "PAID"; paid_on: string | null; days_overdue: number; notes: string | null;
  place_of_supply: string | null;
  items: Array<{ line_no: number; description: string; hsn_sac: string | null; quantity: string; rate: string;
    gst_rate: string; taxable: string; total: string }>;
}
export interface Snapshot {
  bills: number; spend_this_month: string; spend_total: string; overcharged_total: string; gst_claimable: string | null;
  owed_to_you: string; unpaid_invoices: number; overdue_invoices: number;
  spend_by_category: Array<{ category: string; amount: string }>;
  warranties_expiring: Array<{ bill_id: string; vendor: string | null; until: string }>;
}
export interface Deadline { date: string; title: string; detail: string; kind: string; days_left: number }
export interface ChatMsg {
  id: string; role: "user" | "assistant"; content: string;
  meta?: { mode: string; tools: Array<{ tool: string; args: Record<string, unknown> }>;
    cards: Array<{ tool: string; result: Record<string, unknown> }>; disclaimer: string } | null;
}
export interface RegimeResult {
  regime: string; label: string; gross_income: number; standard_deduction: number; taxable_income: number;
  tax_on_slabs: number; rebate: number; marginal_relief: number; cess: number; total_tax: number;
  deductions: Array<{ key: string; label: string; claimed: number; allowed: number }>;
  slab_breakdown: Array<{ from: number; to: number | null; rate: number; amount: number; tax: number }>;
  notes: string[];
}
export interface Comparison {
  financial_year: string; old: RegimeResult; new: RegimeResult; better: "old" | "new"; saving: number;
  summary: string; balance_payable: number;
}

export const app = {
  signup: (b: Record<string, unknown>) => call<Me>("/auth/signup", { method: "POST", body: json(b) }),
  login: (email: string, password: string) => call<Me>("/auth/login", { method: "POST", body: json({ email, password }) }),
  logout: () => call<void>("/auth/logout", { method: "POST" }),
  me: () => call<Me>("/me"),
  updateMe: (b: Partial<Me>) => call<Me>("/me", { method: "PATCH", body: json(b) }),
  states: () => call<Array<{ code: string; name: string }>>("/states"),
  home: () => call<{ me: Me; snapshot: Snapshot; recent_bills: BillRow[]; deadlines: Deadline[]; suggestions: string[] }>("/home"),
  bills: (q?: string, category?: string) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (category) p.set("category", category);
    return call<BillRow[]>(`/bills${p.toString() ? `?${p}` : ""}`);
  },
  uploadBill: (file: File) => { const f = new FormData(); f.append("file", file); return call<BillDetail>("/bills", { method: "POST", body: f }); },
  bill: (id: string) => call<BillDetail>(`/bills/${id}`),
  updateBill: (id: string, b: Record<string, unknown>) => call<BillDetail>(`/bills/${id}`, { method: "PATCH", body: json(b) }),
  deleteBill: (id: string) => call<void>(`/bills/${id}`, { method: "DELETE" }),
  invoices: () => call<SalesInvoice[]>("/invoices"),
  createInvoice: (b: Record<string, unknown>) => call<SalesInvoice>("/invoices", { method: "POST", body: json(b) }),
  markPaid: (id: string, paid_on?: string | null) => call<SalesInvoice>(`/invoices/${id}/paid`, { method: "POST", body: json({ paid_on: paid_on ?? null }) }),
  deleteInvoice: (id: string) => call<void>(`/invoices/${id}`, { method: "DELETE" }),
  taxProfile: () => call<{ inputs: Record<string, number | string | boolean>; financial_year: string;
    deduction_caps: Record<string, { label: string; cap: number | null }> }>("/tax/profile"),
  compare: (b: Record<string, unknown>) => call<Comparison>("/tax/compare", { method: "POST", body: json(b) }),
  gstCheck: (b: Record<string, unknown>) => call<{ required: boolean; threshold: number; turnover: number;
    headroom: number; reasons: string[]; note: string }>("/tax/gst-registration", { method: "POST", body: json(b) }),
  advance: () => call<{ required: boolean; liability: number; note: string; based_on?: string;
    instalments: Array<{ due_date: string; cumulative_percent: number; pay_now: number; status: string }> }>(
    "/tax/advance", { method: "POST", body: json({}) }),
  presumptive: (b: Record<string, unknown>) => call<{ label: string; eligible: boolean; deemed_income: number;
    receipts: number; limit: number; note: string }>("/tax/presumptive", { method: "POST", body: json(b) }),
  deadlines: () => call<Deadline[]>("/deadlines"),
  chatHistory: () => call<{ messages: ChatMsg[]; suggestions: string[] }>("/assistant/history"),
  ask: (message: string) => call<ChatMsg>("/assistant", { method: "POST", body: json({ message }) }),
  clearChat: () => call<void>("/assistant/history", { method: "DELETE" }),
};

export function inr(v: string | number | null | undefined, decimals = false): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: decimals ? 2 : 0, maximumFractionDigits: decimals ? 2 : 0 })}`;
}

export function inrShort(v: string | number | null | undefined): string {
  const n = Number(v ?? 0);
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return inr(n);
}

export function fmtDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
