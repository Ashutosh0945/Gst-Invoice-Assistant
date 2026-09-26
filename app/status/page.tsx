import { probeApi } from "@/lib/api";
import { Card, PageHeader } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function StatusPage() {
  const probe = await probeApi({ fresh: true });
  let db: Record<string, unknown> | null = null;
  if (probe.base) {
    db = await fetch(`${probe.base}/api/v1/health/database`, { cache: "no-store" }).then((r) => r.json()).catch(() => null);
  }
  const env = {
    SITE_URL: process.env.SITE_URL ? process.env.SITE_URL : "not set",
    VERCEL_ENV: process.env.VERCEL_ENV ?? "not on Vercel",
    "Vercel production address": process.env.VERCEL_PROJECT_PRODUCTION_URL ?? "—",
  };
  return (
    <div className="max-w-3xl">
      <PageHeader title="System status" subtitle="Can this website reach its own API and database? Share this page when asking for help." />
      <Card title={probe.ok ? "✅ The website can reach the API" : "❌ The website can't reach the API"}>
        <table className="tbl">
          <thead><tr><th>Address tried</th><th>Result</th></tr></thead>
          <tbody>
            {probe.checks.map((c) => (
              <tr key={c.base}><td className="break-all">{c.base}</td><td className={c.ok ? "text-good" : "text-bad"}>{c.result}</td></tr>
            ))}
          </tbody>
        </table>
        {!probe.ok && (
          <p className="text-sm text-ink-soft mt-4">
            Fix: in Vercel → Settings → Environment Variables, set <b>SITE_URL</b> to your public site address
            (for example https://gst-invoice-assistant.vercel.app), then Deployments → ⋯ → Redeploy.
          </p>
        )}
      </Card>
      <Card className="mt-6" title="Database">
        {db ? <pre className="text-xs whitespace-pre-wrap break-all">{JSON.stringify(db, null, 2)}</pre>
          : <p className="text-sm text-ink-soft">Not checked (the API couldn&apos;t be reached).</p>}
      </Card>
      <Card className="mt-6" title="Settings this server sees">
        <dl className="text-sm space-y-1.5">
          {Object.entries(env).map(([k, v]) => <div key={k} className="flex gap-3"><dt className="text-ink-soft w-56">{k}</dt><dd className="break-all">{v}</dd></div>)}
        </dl>
      </Card>
    </div>
  );
}
