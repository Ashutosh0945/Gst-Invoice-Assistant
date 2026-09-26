import type { Metadata } from "next";
import "@fontsource-variable/plus-jakarta-sans";  // self-hosted: no Google Fonts request at build or runtime
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import Link from "next/link";
import { probeApi } from "@/lib/api";

export const metadata: Metadata = {
  title: "GST Desk",
  description: "AI-assisted GST invoice processing, GSTR-2B reconciliation and input tax credit control",
};

export const dynamic = "force-dynamic";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // If this site's server can't reach its own API, every page would silently look empty.
  // Say so loudly instead.
  const probe = await probeApi().catch(() => ({ ok: false, base: null, checks: [] }));
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <Topbar />
            <main className="flex-1 px-5 md:px-8 pb-12">
              {!probe.ok && (
                <div role="alert" className="mt-6 rounded-2xl border border-bad/40 bg-bad/10 px-5 py-4 text-sm">
                  <b className="text-bad">This site can&apos;t load its data right now,</b> so lists below may look empty even
                  though your invoices are saved. <Link href="/status" className="underline text-white">See what&apos;s wrong</Link>
                </div>
              )}
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
