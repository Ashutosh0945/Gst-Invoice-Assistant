"use client";

import { useEffect, useState } from "react";
import { app, fmtDate, inr, type Comparison, type Deadline } from "@/lib/client";
import { useMe } from "@/components/AppShell";
import { Card, ErrorNote } from "@/components/ui";

type Inputs = Record<string, string>;
const FIELDS: Array<[string, string, string?]> = [
  ["salary_income", "Yearly salary (before deductions)"], ["business_income", "Business / freelance profit"],
  ["other_income", "Other income (interest, rent…)"], ["tds_paid", "Tax already deducted (TDS)"],
];
const DEDS: Array<[string, string]> = [
  ["sec_80c", "80C: PF, PPF, ELSS, LIC, tuition"], ["sec_80d_self", "80D: health insurance (you)"],
  ["sec_80d_parents", "80D: health insurance (parents)"], ["sec_80ccd_1b", "80CCD(1B): extra NPS"],
  ["home_loan_interest", "Home loan interest"], ["hra_exempt", "HRA exemption"],
];

export default function Tax() {
  const { me } = useMe();
  const [inp, setInp] = useState<Inputs>({ age_band: "below_60" });
  const [res, setRes] = useState<Comparison | null>(null);
  const [fy, setFy] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deadlines, setDeadlines] = useState<Deadline[]>([]);

  useEffect(() => {
    app.taxProfile().then((p) => {
      setFy(p.financial_year);
      const saved = Object.fromEntries(Object.entries(p.inputs).map(([k, v]) => [k, String(v)]));
      setInp((s) => ({ ...s, ...saved }));
      if (Object.keys(p.inputs).length) app.compare(p.inputs).then(setRes).catch(() => undefined);
    }).catch((e) => setError(e.message));
    app.deadlines().then(setDeadlines).catch(() => undefined);
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const nums = Object.fromEntries(Object.entries(inp).map(([k, v]) => [k, k === "age_band" ? v : Number(String(v).replace(/,/g, "")) || 0]));
    if (!nums.salary_income && !nums.business_income && !nums.other_income) return setError("Enter at least one kind of income.");
    setBusy(true);
    setError(null);
    try { setRes(await app.compare(nums)); } catch (err) { setError(err instanceof Error ? err.message : "Couldn't calculate."); } finally { setBusy(false); }
  }

  const field = (k: string, label: string) => (
    <label key={k} className="block"><span className="text-sm text-ink-soft">{label}</span>
      <input className="field mt-1.5" inputMode="numeric" placeholder="0" value={inp[k] ?? ""}
        onChange={(e) => { setInp({ ...inp, [k]: e.target.value.replace(/[^\d.]/g, "") }); setError(null); }} /></label>
  );

  return (
    <div>
      <header className="pt-8 pb-6">
        <h1 className="text-[28px] font-extrabold tracking-tight">Tax planner</h1>
        <p className="text-ink-soft mt-1">Official slabs for FY {fy || "—"}. Your answers are saved so the assistant can use them.</p>
      </header>

      <div className="grid gap-6 xl:grid-cols-[1fr_400px]">
        <form onSubmit={run} className="space-y-6 min-w-0" noValidate>
          <Card title="Your income (yearly)">
            <div className="grid sm:grid-cols-2 gap-4">
              {FIELDS.map(([k, l]) => field(k, l))}
              <label className="block"><span className="text-sm text-ink-soft">Your age</span>
                <select className="field mt-1.5" value={inp.age_band} onChange={(e) => setInp({ ...inp, age_band: e.target.value })}>
                  <option value="below_60">Below 60</option><option value="60_to_80">60 to 80</option><option value="above_80">Above 80</option>
                </select></label>
            </div>
          </Card>
          <Card title="Deductions (count only in the old regime)">
            <div className="grid sm:grid-cols-2 gap-4">{DEDS.map(([k, l]) => field(k, l))}</div>
          </Card>
          {error && <ErrorNote>{error}</ErrorNote>}
          <button className="btn-primary w-full sm:w-auto px-8 py-3" disabled={busy}>{busy ? "Calculating…" : "Compare regimes"}</button>
        </form>

        <div className="space-y-6">
          <Card title="Result">
            {!res ? <p className="text-sm text-ink-soft">Fill in your income and press Compare.</p> : (
              <>
                <p className="text-lg font-bold">{res.summary}</p>
                <div className="grid grid-cols-2 gap-3 mt-4">
                  {(["new", "old"] as const).map((r) => (
                    <div key={r} className={`rounded-2xl p-4 ${res.better === r ? "bg-good/10 ring-1 ring-good/40" : "neu-inset"}`}>
                      <div className="text-sm text-ink-soft">{res[r].label}</div>
                      <div className="text-2xl font-extrabold tabular mt-1">{inr(res[r].total_tax)}</div>
                      <div className="text-xs text-ink-faint mt-1">on taxable {inr(res[r].taxable_income)}</div>
                    </div>
                  ))}
                </div>
                <details className="mt-4 text-sm">
                  <summary className="cursor-pointer text-accent-soft">How this was worked out</summary>
                  {(["new", "old"] as const).map((r) => (
                    <div key={r} className="mt-3">
                      <div className="font-semibold">{res[r].label}</div>
                      <ul className="text-ink-soft mt-1 space-y-0.5">
                        <li>Income {inr(res[r].gross_income)} − standard deduction {inr(res[r].standard_deduction)}
                          {res[r].deductions.length ? ` − deductions ${inr(res[r].deductions.reduce((s, d) => s + d.allowed, 0))}` : ""}</li>
                        {res[r].slab_breakdown.filter((s) => s.tax > 0).map((s, i) => <li key={i}>{s.rate}% on {inr(s.amount)} = {inr(s.tax)}</li>)}
                        {res[r].rebate > 0 && <li>Rebate (87A): −{inr(res[r].rebate)}</li>}
                        {res[r].marginal_relief > 0 && <li>Marginal relief: −{inr(res[r].marginal_relief)}</li>}
                        <li>Health &amp; education cess 4%: {inr(res[r].cess)}</li>
                        {res[r].notes.map((n, i) => <li key={`n${i}`} className="text-warn">{n}</li>)}
                      </ul>
                    </div>
                  ))}
                </details>
                {res.balance_payable > 0 && <p className="text-sm mt-4">Still to pay after TDS: <b>{inr(res.balance_payable)}</b></p>}
              </>
            )}
          </Card>
          {me.profile_type !== "individual" && <GstCheck freelancer={me.profile_type === "freelancer"} />}
          <Card title="Your tax calendar">
            <ul className="space-y-2.5">
              {deadlines.slice(0, 8).map((d) => (
                <li key={d.date + d.title} className="flex justify-between gap-3 text-sm">
                  <span><span className="font-semibold">{d.title}</span><span className="block text-xs text-ink-soft">{d.detail}</span></span>
                  <span className={`whitespace-nowrap ${d.days_left <= 7 ? "text-bad font-semibold" : "text-ink-soft"}`}>{fmtDate(d.date)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}

function GstCheck({ freelancer }: { freelancer: boolean }) {
  const [turnover, setTurnover] = useState("");
  const [type, setType] = useState(freelancer ? "services" : "goods");
  const [interstate, setInterstate] = useState(false);
  const [r, setR] = useState<{ required: boolean; reasons: string[]; note: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <Card title="Do I need GST registration?">
      <div className="space-y-3">
        <label className="block"><span className="text-sm text-ink-soft">Yearly turnover (₹)</span>
          <input className="field mt-1.5" inputMode="numeric" value={turnover} onChange={(e) => { setTurnover(e.target.value.replace(/[^\d]/g, "")); setError(null); }} placeholder="e.g. 1800000" /></label>
        <label className="block"><span className="text-sm text-ink-soft">You sell</span>
          <select className="field mt-1.5" value={type} onChange={(e) => setType(e.target.value)}><option value="services">Services</option><option value="goods">Goods</option></select></label>
        {type === "goods" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={interstate} onChange={(e) => setInterstate(e.target.checked)} /> I sell goods to other states</label>}
        <button className="btn w-full" onClick={async () => {
          if (!turnover) { setError("Enter your yearly turnover."); return; }
          try { setR(await app.gstCheck({ turnover: Number(turnover), supply_type: type, interstate_goods: interstate })); } catch (e) { setError(e instanceof Error ? e.message : "Failed."); }
        }}>Check</button>
        {error && <ErrorNote>{error}</ErrorNote>}
        {r && <div className={`rounded-xl p-3 text-sm ${r.required ? "bg-warn/10" : "bg-good/10"}`}>
          <b>{r.required ? "Yes, you need to register." : "Not required yet."}</b> {r.reasons.join(" ")} <span className="text-ink-soft">{r.note}</span></div>}
      </div>
    </Card>
  );
}
