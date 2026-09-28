import type { NextConfig } from "next";

// A Vercel build without the API URL would ship a site that can't reach its
// backend (see src/lib/config.ts) — fail that build outright instead. Only
// on Vercel: CI and local builds legitimately run without it.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error("NEXT_PUBLIC_API_URL must be set for a Vercel build.");
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
