"use client";

import { useSyncExternalStore } from "react";
import { CURRENCY_KEY, THEME_COLORS, THEME_KEY } from "./themeScript";

// Display preferences that have to be right before the account has loaded:
// the theme (or the page flashes the wrong colours) and the currency symbol
// (or every amount flickers). Both live on the account (/users/me) and are
// cached on the device, so the next page load starts from the last answer
// and reconciles once the account arrives — see PreferencesSync.

export type ThemePref = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const CURRENCY_SYMBOLS = ["$", "S$", "RM", "HK$", "NT$", "A$", "US$", "£", "€", "¥"] as const;

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* this device just won't remember it between loads */
  }
}

const isThemePref = (v: unknown): v is ThemePref => v === "system" || v === "light" || v === "dark";

// Module state, so plain functions like money() can read it without a hook.
// Starts at the defaults the server renders with; PreferencesSync loads the
// cached values right after hydration so the first client render matches
// the server's.
let themePref: ThemePref = "system";
let currencySymbol = "$";
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function systemPrefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolveTheme(pref: ThemePref): ResolvedTheme {
  if (pref === "system") return systemPrefersDark() ? "dark" : "light";
  return pref;
}

/** Marks <html> and the browser bar. Transitions are paused for the frame
 * so cards and buttons don't each fade across separately. */
export function applyTheme(pref: ThemePref): void {
  const root = document.documentElement;
  const resolved = resolveTheme(pref);
  if (root.getAttribute("data-theme") !== resolved) {
    root.classList.add("theme-switching");
    root.setAttribute("data-theme", resolved);
    requestAnimationFrame(() => root.classList.remove("theme-switching"));
  }
  root.setAttribute("data-theme-pref", pref);
  document
    .querySelectorAll('meta[name="theme-color"]')
    .forEach((m) => m.setAttribute("content", THEME_COLORS[resolved]));
}

/** Reads the device's cached answers into the store and onto the page. */
export function loadCachedPreferences(): void {
  const cachedTheme = read(THEME_KEY);
  themePref = isThemePref(cachedTheme) ? cachedTheme : "system";
  const cachedSymbol = read(CURRENCY_KEY);
  currencySymbol = cachedSymbol && (CURRENCY_SYMBOLS as readonly string[]).includes(cachedSymbol) ? cachedSymbol : "$";
  applyTheme(themePref);
  emit();
}

export function setThemePref(pref: ThemePref): void {
  themePref = pref;
  write(THEME_KEY, pref);
  applyTheme(pref);
  emit();
}

export function setCurrencySymbol(symbol: string): void {
  if (symbol === currencySymbol) return;
  currencySymbol = symbol;
  write(CURRENCY_KEY, symbol);
  emit();
}

export function getCurrencySymbol(): string {
  return currencySymbol;
}

export function getThemePref(): ThemePref {
  return themePref;
}

/**
 * The symbol money() is using. Pages that show amounts call this so they
 * re-render when it changes — money() itself is a plain function and can't
 * subscribe. The server snapshot is the default, which keeps hydration
 * consistent.
 */
export function useCurrencySymbol(): string {
  return useSyncExternalStore(subscribe, getCurrencySymbol, () => "$");
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, getThemePref, () => "system");
}
