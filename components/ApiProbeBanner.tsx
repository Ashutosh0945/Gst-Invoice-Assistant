import Link from "next/link";
import { probeApi } from "@/lib/api";

// Streams in after the page shell, so a slow/cold API never delays navigation.
export async function ApiProbeBanner() {
  const probe = await probeApi().catch(() => ({ ok: false, base: null, checks: [] }));
  if (probe.ok) return null;
  return (
    <div role="alert" className="mt-6 rounded-2xl border border-bad/40 bg-bad/10 px-5 py-4 text-sm">
      <b className="text-bad">This site can&apos;t load its data right now,</b> so lists below may look empty even
      though your invoices are saved. <Link href="/status" className="underline text-ink-strong">See what&apos;s wrong</Link>
    </div>
  );
}
