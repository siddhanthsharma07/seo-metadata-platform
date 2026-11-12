import type { NextConfig } from "next";

const backend = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  // The browser talks to /api on the same origin; Next proxies to FastAPI.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  poweredByHeader: false,
};

export default nextConfig;
