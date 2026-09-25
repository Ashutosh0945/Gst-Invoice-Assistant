import type { Metadata } from "next";
import "@fontsource-variable/plus-jakarta-sans";
import "./globals.css";
import { brand, hexToRgbTriplet, lighten } from "@/lib/brand";

export const metadata: Metadata = {
  title: { default: `${brand.name} Console`, template: `%s · ${brand.name} Console` },
  description: brand.tagline,
  robots: { index: false, follow: false },   // a private workspace: keep it out of search engines
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const accent = hexToRgbTriplet(brand.accent);
  const style = { "--accent": accent, "--accent-soft": lighten(accent) } as React.CSSProperties;
  return (
    <html lang="en" style={style}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
