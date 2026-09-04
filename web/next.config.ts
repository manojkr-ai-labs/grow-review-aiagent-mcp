import type { NextConfig } from "next";

// Evaluated at `next build` (routes-manifest). Set REVIEWPULSE_API_ORIGIN on the
// web service before build, e.g. http://reviewpulse-api.railway.internal:8080.
const apiOrigin = process.env.REVIEWPULSE_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiOrigin}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
