// Shared with the root layout, a Server Component — which is why this isn't
// in preferences.ts: everything a "use client" module exports reaches a
// Server Component as a client reference, never as the string itself.

type ResolvedTheme = "light" | "dark";

export const THEME_KEY = "gambrole_theme";
export const CURRENCY_KEY = "gambrole_currency";

/** The browser bar's colour per resolved theme — the same as --background. */
export const THEME_COLORS: Record<ResolvedTheme, string> = {
  light: "#f7f5f0",
  dark: "#0e1512",
};

/**
 * Runs in <head> before first paint (see layout.tsx): reads the cached
 * preference, resolves "system" against the OS, and marks <html>. Kept tiny
 * and dependency-free since it's inlined as a string; applyTheme in
 * preferences.ts is its in-app twin and must agree with it.
 */
export const THEME_SCRIPT = `(function(){try{var p=localStorage.getItem("${THEME_KEY}");var d=p==="dark"||(p!=="light"&&window.matchMedia("(prefers-color-scheme: dark)").matches);var t=d?"dark":"light";var e=document.documentElement;e.setAttribute("data-theme",t);var m=document.querySelectorAll('meta[name="theme-color"]');for(var i=0;i<m.length;i++)m[i].setAttribute("content",d?"${THEME_COLORS.dark}":"${THEME_COLORS.light}")}catch(_){}})()`;


/**
 * Also in <head> before first paint: inside the iOS app (Capacitor injects
 * window.Capacitor before any page script), marks <html class="native"> for
 * the app-only CSS in globals.css and turns off pinch/double-tap zoom. A
 * browser tab keeps zoom — that's an accessibility feature there.
 */
export const NATIVE_SCRIPT = `(function(){try{var c=window.Capacitor;if(!c||!c.isNativePlatform||!c.isNativePlatform())return;document.documentElement.classList.add("native");var v=document.querySelector('meta[name="viewport"]');if(v)v.setAttribute("content",v.getAttribute("content")+", maximum-scale=1, user-scalable=no")}catch(_){}})()`;
