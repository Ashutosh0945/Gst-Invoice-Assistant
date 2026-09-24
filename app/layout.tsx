import type { Metadata } from "next";
import "@fontsource-variable/plus-jakarta-sans";  // self-hosted: no Google Fonts request at build or runtime
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";

export const metadata: Metadata = {
  title: "GST Desk",
  description: "AI-assisted GST invoice processing, GSTR-2B reconciliation and input tax credit control",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex-1 min-w-0 flex flex-col">
            <Topbar />
            <main className="flex-1 px-5 md:px-8 pb-12">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
