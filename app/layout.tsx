import type { Metadata } from "next";
import "@fontsource-variable/plus-jakarta-sans";  // self-hosted: no Google Fonts request at build or runtime
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { themeBootScript } from "@/components/ThemeToggle";
import { PwaManager } from "@/components/PwaManager";
import { Suspense } from "react";
import { ApiProbeBanner } from "@/components/ApiProbeBanner";

export const metadata: Metadata = {
  title: "GST Desk",
  description: "AI-assisted GST invoice processing, GSTR-2B reconciliation and input tax credit control",
};

export const dynamic = "force-dynamic";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
        <link rel="manifest" href="/manifest.webmanifest" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />
        <meta name="theme-color" content="#1E1D35" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="GST Desk" />
      </head>
      <body className="font-sans antialiased">
        <PwaManager />
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <Topbar />
            <main className="flex-1 px-5 md:px-8 pb-12">
              <Suspense fallback={null}><ApiProbeBanner /></Suspense>
              {children}
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
