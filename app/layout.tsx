import type { Metadata, Viewport } from "next";
import "@fontsource-variable/plus-jakarta-sans";
import "./globals.css";
import { brand, hexToRgbTriplet, lighten } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: `${brand.name} — ${brand.tagline}`, template: `%s · ${brand.name}` },
  description: "Snap your bills, ask tax questions, send invoices and never miss a deadline — with an AI accountant that uses verified tax rules.",
};

export const viewport: Viewport = { themeColor: "#1E1D35", width: "device-width", initialScale: 1, viewportFit: "cover" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const accent = hexToRgbTriplet(brand.accent);
  const style = { "--accent": accent, "--accent-soft": lighten(accent) } as React.CSSProperties;
  return (
    <html lang="en" style={style}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
