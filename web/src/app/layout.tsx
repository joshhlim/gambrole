import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Outfit } from "next/font/google";
import "./globals.css";
import RouteTransition from "@/components/RouteTransition";
import Backdrop from "@/components/Backdrop";
import TopBar from "@/components/TopBar";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Display face for headings and the logo — rounder and more characterful
// than the body sans, without costing legibility on the numbers, which
// stay on Geist. See globals.css.
const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "GamBROle",
  description: "Live score keeping for game night — Taidi, mahjong, poker",
};

export const viewport: Viewport = {
  themeColor: "#1e3a2f",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${outfit.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Backdrop />
        {/* Outside RouteTransition on purpose: the bar is the one fixed
            point on every screen, so pages slide underneath it rather
            than carrying it along. It hides itself when signed out. */}
        <TopBar />
        <RouteTransition>{children}</RouteTransition>
      </body>
    </html>
  );
}
