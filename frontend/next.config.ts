import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Backend proxy is handled by /api/backend/[...path]/route.ts
  // which injects the Supabase auth token server-side.
};

export default nextConfig;
