"use client";

import { useEffect, useLayoutEffect } from "react";
import { useMe } from "@/lib/me";
import {
  applyTheme,
  getThemePref,
  loadCachedPreferences,
  setCurrencySymbol,
  setThemePref,
} from "@/lib/preferences";

/**
 * Keeps the page's theme and currency in step with the account. Renders
 * nothing; mounted once in the root layout.
 *
 * The inline script in layout.tsx has already painted the cached theme;
 * this loads the same cache into the store (in a layout effect, so React's
 * dev-mode remount — which resets <html>'s attributes — can't leave a
 * frame of the wrong theme), follows the OS while the choice is "system",
 * and adopts the account's choices once /users/me arrives.
 */
export default function PreferencesSync() {
  const me = useMe();
  const accountTheme = me?.preferences.theme;
  const accountSymbol = me?.preferences.currency_symbol;

  useLayoutEffect(() => {
    loadCachedPreferences();
  }, []);

  useEffect(() => {
    let mq: MediaQueryList;
    try {
      mq = window.matchMedia("(prefers-color-scheme: dark)");
    } catch {
      return;
    }
    const follow = () => {
      if (getThemePref() === "system") applyTheme("system");
    };
    mq.addEventListener("change", follow);
    return () => mq.removeEventListener("change", follow);
  }, []);

  // Only when the account's value itself changes — not on every profile
  // update — so an optimistic switch in Settings isn't undone by a stale
  // profile landing before the save does.
  useEffect(() => {
    if (accountTheme && accountTheme !== getThemePref()) setThemePref(accountTheme);
  }, [accountTheme]);

  useEffect(() => {
    if (accountSymbol) setCurrencySymbol(accountSymbol);
  }, [accountSymbol]);

  return null;
}
