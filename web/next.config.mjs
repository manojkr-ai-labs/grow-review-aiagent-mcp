/** @type {import('next').NextConfig} */
// Evaluated at `next build` (routes-manifest). Set REVIEWPULSE_API_ORIGIN on the
// web service before build, e.g. http://reviewpulse-api.railway.internal:8080.
const apiOrigin = process.env.REVIEWPULSE_API_ORIGIN || "http://127.0.0.1:8000";

const nextConfig = {
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return {
      beforeFiles: [
        // Job history lives at app/history so Railway/gitignore `runs/` rules
        // cannot drop the route. Public URL stays /runs.
        { source: "/runs", destination: "/history" },
        { source: "/runs/:runId", destination: "/history?run=:runId" },
      ],
      afterFiles: [
        {
          source: "/api/v1/:path*",
          destination: `${apiOrigin}/api/v1/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
