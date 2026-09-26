// Thin fetch wrapper around the FastAPI backend.
//
// Client Components (the browser) can always use a relative "/api/v1/..."
// path -- the browser resolves it against the page's own origin, which then
// hits the Next.js server itself: next.config.mjs's rewrite forwards it to
// FastAPI in local dev, and vercel.json's rewrite does the same in
// production. No absolute URL or CORS handling needed there.
//
// Server Components are different: they run inside Node during SSR, and
// Node's fetch() has no "current page" to resolve a relative URL against --
// it throws. So server-side calls need an absolute URL: hit the FastAPI
// dev server directly on localhost in dev, and hit this same Vercel
// deployment's own public URL (via the auto-populated VERCEL_URL) in
// production. getBaseUrl() below picks the right one; everything else in
// this file is unaware of the distinction.
function getBaseUrl(): string {
  if (typeof window !== "undefined") return ""; // browser: relative path is correct
  return serverBaseCandidates()[0];
}

/** Every address the server could use to reach this site's API, best first. On Vercel the
 *  per-deployment address (VERCEL_URL) is usually behind Vercel's login ("Deployment
 *  Protection"), so the public addresses come first. */
export function serverBaseCandidates(): string[] {
  const list: string[] = [];
  const add = (u?: string | null) => {
    if (!u) return;
    const v = (u.startsWith("http") ? u : `https://${u}`).replace(/\/$/, "");
    if (!list.includes(v)) list.push(v);
  };
  add(process.env.SITE_URL?.trim());
  if (process.env.VERCEL) {
    if (process.env.VERCEL_ENV === "production") add(process.env.VERCEL_PROJECT_PRODUCTION_URL);
    add(process.env.VERCEL_BRANCH_URL);
    add(process.env.VERCEL_URL);
    add(process.env.VERCEL_PROJECT_PRODUCTION_URL);
  }
  add(process.env.BACKEND_URL || "http://localhost:8000"); // local development
  return list;
}

let workingBase: string | null = null;   // remembered per server instance once found

/** Vercel's login wall answers with 401/403 and an HTML page; the API always answers JSON. */
function blockedByLoginWall(res: Response): boolean {
  return (res.status === 401 || res.status === 403) && !(res.headers.get("content-type") || "").includes("json");
}

// Preview deployments stay behind Vercel's login; if "Protection Bypass for Automation" is
// enabled, Vercel provides this secret and server-side fetches can pass through.
function serverHeaders(): Record<string, string> {
  if (typeof window !== "undefined") return {};
  const bypass = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
  return bypass ? { "x-vercel-protection-bypass": bypass } : {};
}

export type InvoiceStatus =
  | "PROCESSING" | "NEEDS_REVIEW" | "AUTO_APPROVED" | "APPROVED" | "REJECTED" | "FAILED";

export interface InvoiceSummary {
  id: string;
  source_filename: string;
  vendor_name_raw: string | null;
  vendor_gstin_raw: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  grand_total: string | null;
  status: InvoiceStatus;
  confidence_score: string | null;
  created_at: string;
  einvoice_status: string | null;
  gstr2b_status: string | null;
}

export interface Finding {
  id: string;
  code: string;
  category: string;
  severity: "INFO" | "WARNING" | "ERROR";
  message: string;
  field: string | null;
  line_no: number | null;
}

export interface InvoiceLineOut {
  id: string;
  line_no: number;
  description: string | null;
  hsn_sac: string | null;
  quantity: string | null;
  unit_price: string | null;
  taxable_value: string | null;
  gst_rate: string | null;
  cgst: string | null;
  sgst: string | null;
  igst: string | null;
  line_total: string | null;
  confidence: number;
}

export interface ReconciliationRow {
  id: string;
  invoice_line_no: number | null;
  po_line_no: number | null;
  status: string;
  qty_invoiced: string | null;
  qty_po: string | null;
  price_invoiced: string | null;
  price_po: string | null;
  variance_pct: string | null;
}

export interface InvoiceDetail extends InvoiceSummary {
  po_number_raw: string | null;
  llm_explanation: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_notes: string | null;
  items: InvoiceLineOut[];
  findings: Finding[];
  reconciliation: ReconciliationRow[];
  buyer_gstin_raw: string | null;
  subtotal: string | null;
  total_cgst: string | null;
  total_sgst: string | null;
  total_igst: string | null;
  irn: string | null;
  einvoice_data: { payload: Record<string, unknown> | null; comparisons: QrComparison[];
    signature_checked: boolean; signature_valid: boolean | null } | null;
  payment_date: string | null;
  itc: ItcAssessment | null;
}

export interface QrComparison { field: string; qr: string | null; invoice: string | null; match: boolean | null }
export interface ItcReason { code: string; severity: "INFO" | "WARNING" | "ERROR"; message: string; line_no: number | null }
export interface ItcAssessment {
  status: string; total_itc: string; eligible_itc: string; blocked_itc: string; review_itc: string;
  at_risk_itc: string; claim_deadline: string | null; payment_due_by: string | null; reasons: ItcReason[] | null;
}
export interface ItcRow extends ItcAssessment {
  invoice_id: string; invoice_number: string | null; vendor_name: string | null; vendor_gstin: string | null;
  invoice_date: string | null; grand_total: string | null; gstr2b_status: string | null; payment_date: string | null;
}
export interface ItcSummary {
  total_itc: string; eligible_itc: string; blocked_itc: string; review_itc: string; at_risk_itc: string;
  credit_at_risk: string;
  by_status: Array<{ status: string; invoice_count: number; total_itc: string; eligible_itc: string;
    blocked_itc: string; review_itc: string; at_risk_itc: string }>;
}
export interface Gstr2bImport {
  id: string; return_period: string; gstin: string | null; source_filename: string; generated_on: string | null;
  record_count: number; imported_at: string; total_tax: string; status_counts: Record<string, number>;
  missing_in_2b: number;
}
export interface Gstr2bRecord {
  id: string; supplier_gstin: string; supplier_name: string | null; invoice_number: string; invoice_date: string | null;
  taxable_value: string | null; total_tax: string; itc_available: boolean; itc_unavailable_reason: string | null;
  reverse_charge: boolean; match_status: string; match_score: string | null; match_notes: string | null;
  matched_invoice_id: string | null;
}
export interface MissingIn2b {
  invoice_id: string; invoice_number: string | null; vendor_name: string | null; vendor_gstin: string | null;
  invoice_date: string | null; grand_total: string | null; at_risk_itc: string | null;
}
export interface EinvRow {
  invoice_id: string; invoice_number: string | null; vendor_name: string | null; grand_total: string | null;
  irn: string | null; einvoice_status: string | null; comparisons: QrComparison[];
}
export interface EinvResult {
  status: string; irn: string | null; data: Record<string, unknown> | null; signature_checked: boolean;
  signature_valid: boolean | null; comparisons: QrComparison[];
  findings: Array<{ code: string; severity: string; message: string }>;
}
export interface VendorRisk {
  vendor_gstin: string; vendor_name: string | null; invoice_count: number; total_spend: string;
  filing_rate: number | null; missing_in_2b: number; amount_mismatches: number; einvoice_issues: number;
  error_findings: number; at_risk_itc: string; risk_score: number; risk_level: "Low" | "Medium" | "High";
  reasons: string[];
}
export interface BenchmarkLayout {
  documents: number; field_accuracy: number | null; header_accuracy: number | null; line_item_accuracy: number | null;
  item_count_accuracy: number; perfect_documents: number; ms_per_document: number; per_field: Record<string, number>;
}
export interface Benchmark {
  generated_at: string; documents_per_layout: number; layouts: string[]; layoutlm_model: string | null;
  extractors: Record<string, { overall_field_accuracy: number | null; layouts: Record<string, BenchmarkLayout> }>;
}
export interface Overview {
  itc: ItcSummary;
  itc_by_month: Array<{ month: string; eligible: string; blocked: string; review: string; at_risk: string }>;
  latest_gstr2b: Gstr2bImport | null;
  einvoice_counts: Record<string, number>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const opts: RequestInit = {
    ...init,
    headers: { "Content-Type": "application/json", ...serverHeaders(), ...(init?.headers || {}) },
    cache: "no-store",
  };
  let res: Response | null = null;
  if (typeof window !== "undefined") {
    res = await fetch(path, opts);
  } else {
    const bases = workingBase ? [workingBase, ...serverBaseCandidates().filter((b) => b !== workingBase)] : serverBaseCandidates();
    let lastErr: unknown = null;
    for (const base of bases) {
      try {
        const r = await fetch(`${base}${path}`, opts);
        if (blockedByLoginWall(r)) { lastErr = new Error(`${r.status} blocked by Vercel login at ${base}`); continue; }
        res = r;
        workingBase = base;
        break;
      } catch (e) {
        lastErr = e;
      }
    }
    if (!res) {
      console.error(`[api] could not reach the API for ${path}:`, lastErr);
      throw new Error(`503 API unreachable: ${lastErr instanceof Error ? lastErr.message : String(lastErr)}`);
    }
  }
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

/** Used by the layout banner and the /status page: which API addresses work from the server. */
let probeCache: { at: number; value: { ok: boolean; base: string | null;
  checks: Array<{ base: string; result: string; ok: boolean }> } } | null = null;

export async function probeApi(opts: { fresh?: boolean } = {}): Promise<{ ok: boolean; base: string | null;
  checks: Array<{ base: string; result: string; ok: boolean }> }> {
  // A good result is remembered for 5 minutes so pages don't pay for this check on every load.
  if (!opts.fresh && probeCache && probeCache.value.ok && Date.now() - probeCache.at < 5 * 60_000) return probeCache.value;
  const value = await runProbe();
  probeCache = { at: Date.now(), value };
  return value;
}

async function runProbe(): Promise<{ ok: boolean; base: string | null;
  checks: Array<{ base: string; result: string; ok: boolean }> }> {
  const checks: Array<{ base: string; result: string; ok: boolean }> = [];
  for (const base of serverBaseCandidates()) {
    try {
      const r = await fetch(`${base}/api/v1/health`, { cache: "no-store", headers: serverHeaders() });
      const ok = r.ok && (r.headers.get("content-type") || "").includes("json");
      checks.push({ base, ok, result: ok ? "works" : blockedByLoginWall(r) ? `blocked by Vercel login (${r.status})` : `HTTP ${r.status}` });
      if (ok) { workingBase = workingBase ?? base; return { ok: true, base, checks }; }
    } catch (e) {
      checks.push({ base, ok: false, result: `can't connect (${e instanceof Error ? e.message : "error"})` });
    }
  }
  return { ok: false, base: null, checks };
}

export const api = {
  listInvoices: (params: { status?: string; limit?: number; vendor_gstin?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.limit) qs.set("limit", String(params.limit));
    if (params.vendor_gstin) qs.set("vendor_gstin", params.vendor_gstin);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<InvoiceSummary[]>(`/api/v1/invoices${suffix}`);
  },
  getInvoice: (id: string) => request<InvoiceDetail>(`/api/v1/invoices/${id}`),
  uploadInvoice: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${getBaseUrl()}/api/v1/invoices`, { method: "POST", body: form }).then(async (res) => {
      if (!res.ok) throw new Error(errorText(await res.text(), res.status));
      return res.json() as Promise<InvoiceDetail>;
    });
  },
  approve: (id: string, reviewer: string, notes?: string) =>
    request<InvoiceDetail>(`/api/v1/invoices/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ reviewer, notes }),
    }),
  reject: (id: string, reviewer: string, notes?: string) =>
    request<InvoiceDetail>(`/api/v1/invoices/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reviewer, notes }),
    }),

  statusSummary: () => request<Array<{
    status: string; invoice_count: number; total_value: string | null; avg_confidence: string | null;
  }>>("/api/v1/analytics/status-summary"),
  dailyIntake: () => request<Array<{
    day: string; invoices_ingested: number; auto_approved: number; needs_review: number; rejected: number;
  }>>("/api/v1/analytics/daily-intake"),
  gstByRate: () => request<Array<{
    gst_rate: string | null; invoice_count: number; total_taxable_value: string | null; total_gst: string | null;
  }>>("/api/v1/analytics/gst-by-rate"),
  hsnSummary: () => request<Array<{
    hsn_sac: string | null; line_count: number; total_taxable_value: string | null; avg_gst_rate: string | null;
  }>>("/api/v1/analytics/hsn-summary"),
  vendorSpend: () => request<Array<{
    vendor_name: string | null; gstin: string | null; invoice_count: number;
    total_spend: string | null; avg_confidence: string | null;
  }>>("/api/v1/analytics/vendor-spend"),
  findingFrequency: () => request<Array<{
    code: string; category: string; severity: string; occurrence_count: number; invoice_count: number;
  }>>("/api/v1/analytics/finding-frequency"),
  reconciliationSummary: () => request<Array<{ status: string; line_count: number }>>(
    "/api/v1/analytics/reconciliation-summary"
  ),
  overview: () => request<Overview>("/api/v1/compliance/overview"),
  itcSummary: () => request<ItcSummary>("/api/v1/itc/summary"),
  itcAssessments: (status?: string) =>
    request<ItcRow[]>(`/api/v1/itc/assessments${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  itcReassess: () => request<{ reassessed: number }>("/api/v1/itc/reassess", { method: "POST" }),
  recordPayment: (id: string, paid_on: string | null) =>
    request<InvoiceDetail>(`/api/v1/invoices/${id}/payment`, { method: "POST", body: JSON.stringify({ paid_on }) }),
  gstr2bImports: () => request<Gstr2bImport[]>("/api/v1/gstr2b/imports"),
  gstr2bRecords: (id: string, status?: string) =>
    request<Gstr2bRecord[]>(`/api/v1/gstr2b/imports/${id}/records${status ? `?status=${status}` : ""}`),
  gstr2bMissing: () => request<MissingIn2b[]>("/api/v1/gstr2b/missing"),
  gstr2bImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${getBaseUrl()}/api/v1/gstr2b/import`, { method: "POST", body: form }).then(async (res) => {
      if (!res.ok) throw new Error(errorText(await res.text(), res.status));
      return res.json() as Promise<Gstr2bImport>;
    });
  },
  gstr2bDelete: (id: string) =>
    fetch(`${getBaseUrl()}/api/v1/gstr2b/imports/${id}`, { method: "DELETE" }).then((r) => {
      if (!r.ok) throw new Error("Could not delete the import.");
    }),
  einvoiceSummary: () => request<{ counts: Record<string, number>; flagged: EinvRow[]; recent: EinvRow[] }>(
    "/api/v1/einvoice/summary"),
  einvoiceVerify: (qr_text: string) =>
    request<EinvResult>("/api/v1/einvoice/verify", { method: "POST", body: JSON.stringify({ qr_text }) }),
  einvoiceVerifyFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${getBaseUrl()}/api/v1/einvoice/verify-file`, { method: "POST", body: form }).then(async (res) => {
      if (!res.ok) throw new Error(errorText(await res.text(), res.status));
      return res.json() as Promise<EinvResult>;
    });
  },
  vendorRisk: () => request<VendorRisk[]>("/api/v1/analytics/vendor-risk"),
  benchmark: () => request<Benchmark>("/api/v1/ml/benchmark"),
  duplicates: () => request<Array<{
    invoice_id: string; invoice_number: string | null; source_filename: string; code: string; message: string;
  }>>("/api/v1/analytics/duplicates"),
};

export function formatMoney(v: string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPercent(v: string | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

function errorText(body: string, status?: number): string {
  // The API explains problems as JSON {"detail": "..."}. Anything else (a host's HTML
  // error page, a bare "Internal Server Error") gets a plain-language message instead.
  try {
    const j = JSON.parse(body);
    if (typeof j.detail === "string") return j.detail;
  } catch { /* not JSON */ }
  if (status === 413) return "That file is too large. Please use a file under 4 MB.";
  if (status === 504) return "The server took too long to read this invoice. Please try again.";
  if (status && status >= 500) return "The server hit an error while processing this invoice. Please try again; if it keeps happening, open /api/v1/health/database on your site to check the database.";
  return body && body.length < 200 && !body.trimStart().startsWith("<") ? body : "The request failed. Please try again.";
}

export function formatCompact(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  if (Number.isNaN(n)) return "—";
  const a = Math.abs(n);
  if (a >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function periodLabel(p: string): string {
  const d = new Date(Number(p.slice(2)), Number(p.slice(0, 2)) - 1, 1);
  return d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}
