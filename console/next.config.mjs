/** @type {import('next').NextConfig} */

// Where the Python API lives. The browser always calls this website's own /api/...
// and Next.js forwards it there, so login cookies stay on one domain.
const backend = process.env.BACKEND_URL || (process.env.VERCEL ? "" : "http://localhost:8000");

if (process.env.VERCEL && !backend) {
  // Fail the Vercel build loudly instead of deploying a site whose every request 404s.
  throw new Error("BACKEND_URL is not set. In Vercel → Settings → Environment Variables, set BACKEND_URL to your Render API address (e.g. https://munshi-api.onrender.com), then redeploy.");
}

const nextConfig = {
  // Reading a scanned invoice (OCR) can take longer than the default 30 s proxy limit.
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend.replace(/\/$/, "")}/api/:path*` }];
  },
};

export default nextConfig;
