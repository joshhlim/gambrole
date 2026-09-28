import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "GamBROle",
    short_name: "GamBROle",
    description: "Live score keeping for game night — Taidi, mahjong, poker",
    start_url: "/",
    display: "standalone",
    background_color: "#F7F5F0",
    theme_color: "#1E3A2F",
    // PNGs alongside the SVG: Android's install prompt wants raster 192 and
    // 512, and "maskable" is the full-bleed one it can crop to any shape.
    // (The iOS home-screen icon is app/apple-icon.png.)
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
