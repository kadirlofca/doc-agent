import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      // Proxy all /api/backend/* to FastAPI, stripping the /backend prefix
      {
        source: "/api/backend/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
