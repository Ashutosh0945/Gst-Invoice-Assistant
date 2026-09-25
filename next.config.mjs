/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // Everywhere except Vercel, proxy /api/* to the FastAPI server so the browser
    // can always call same-origin relative paths (dev, `next start`, Docker).
    // On Vercel, vercel.json routes /api/* to the Python function instead.
    if (process.env.VERCEL) return [];
    const backend = process.env.BACKEND_URL || "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
