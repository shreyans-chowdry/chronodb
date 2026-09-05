import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Proxy /api requests to the FastAPI backend
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/:path*',
      },
    ]
  },
  // Allow cross-origin requests for dev server (e.g. from mobile or other local network devices)
  // @ts-ignore - Some Next.js versions type this under experimental, others top-level
  allowedDevOrigins: ["10.79.172.72"],
};

export default nextConfig;
