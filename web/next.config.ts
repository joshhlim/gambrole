import type { NextConfig } from "next";

// A Vercel build without the API URL would ship a site that can't reach its
// backend (see src/lib/config.ts) — fail that build outright instead. Only
// on Vercel: CI and local builds legitimately run without it.
if (process.env.VERCEL && !process.env.NEXT_PUBLIC_API_URL) {
  throw new Error("NEXT_PUBLIC_API_URL must be set for a Vercel build.");
}

const nextConfig: NextConfig = {
  // Plain static files (out/), so the iOS app can bundle the site with
  // Capacitor. That rules out server features: no dynamic [param] routes
  // (ids go in the query string — lib/routes.ts), no redirects here (old
  // links are redirected in vercel.json instead), no API routes.
  output: "export",
};

export default nextConfig;
