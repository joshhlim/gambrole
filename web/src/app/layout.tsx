import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Outfit } from "next/font/google";
import "./globals.css";
import RouteTransition from "@/components/RouteTransition";
import Backdrop from "@/components/Backdrop";
import TopBar from "@/components/TopBar";
import PreferencesSync from "@/components/PreferencesSync";
import Onboarding from "@/components/Onboarding";
import { THEME_COLORS, THEME_SCRIPT } from "@/lib/themeScript";

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

// Both schemes, so the browser bar matches before any script runs; the
// theme script then overrides both with the account's own choice.
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: THEME_COLORS.light },
    { media: "(prefers-color-scheme: dark)", color: THEME_COLORS.dark },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-theme is set by the script below before paint, so the server's
    // markup never carries it — hence suppressHydrationWarning, which only
    // covers this element's own attributes.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${outfit.variable} h-full antialiased`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <Backdrop />
        {/* Outside RouteTransition on purpose: the bar is the one fixed
            point on every screen, so pages slide underneath it rather
            than carrying it along. It hides itself when signed out. */}
        <TopBar />
        <RouteTransition>{children}</RouteTransition>
        <PreferencesSync />
        <Onboarding />
      </body>
    </html>
  );
}
