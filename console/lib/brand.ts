// White-label settings. Every visible name, colour and logo comes from here, so a
// partner (bank, CA firm, fintech app) can rebrand the product with environment
// variables alone — no code changes. See .env.example (NEXT_PUBLIC_BRAND_*).

export const brand = {
  name: process.env.NEXT_PUBLIC_BRAND_NAME || "GST Desk",
  tagline: process.env.NEXT_PUBLIC_BRAND_TAGLINE || "Invoice checks, GSTR-2B and tax credit control",
  accent: process.env.NEXT_PUBLIC_BRAND_ACCENT || "#7C7CF2",
  logoUrl: process.env.NEXT_PUBLIC_BRAND_LOGO_URL || "",
  supportEmail: process.env.NEXT_PUBLIC_BRAND_SUPPORT_EMAIL || "support@example.com",
  poweredBy: process.env.NEXT_PUBLIC_BRAND_SHOW_POWERED_BY !== "false",
};

/** "#7C7CF2" -> "124 124 242" for Tailwind's rgb(var(--accent) / alpha) colours. */
export function hexToRgbTriplet(hex: string): string {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.padEnd(6, "0").slice(0, 6);
  const n = parseInt(full, 16);
  if (Number.isNaN(n)) return "124 124 242";
  return `${(n >> 16) & 255} ${(n >> 8) & 255} ${n & 255}`;
}

export function lighten(triplet: string, amount = 30): string {
  return triplet.split(" ").map((v) => Math.min(255, Number(v) + amount)).join(" ");
}
