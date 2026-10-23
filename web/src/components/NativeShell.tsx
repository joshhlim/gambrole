"use client";

import { useEffect } from "react";
import { Keyboard } from "@capacitor/keyboard";
import { SplashScreen } from "@capacitor/splash-screen";
import { StatusBar, Style } from "@capacitor/status-bar";
import { useStoredUser } from "@/lib/auth";
import { hapticTap, isNativeApp } from "@/lib/native";

const TAPPABLE = 'button, a[href], [role="button"], [role="menuitem"], [role="tab"], label';

/**
 * The iOS app's native chrome: hides the splash once the first screen is
 * ready to show, keeps the status bar legible in either theme, drops the keyboard's
 * ↑ ↓ ✓ bar, and gives every button a light tick. Renders nothing, and
 * does nothing at all in a browser.
 */
export default function NativeShell() {
  // Pages render nothing until they know whether you're signed in, so the
  // splash waits for that too — otherwise it fades to an empty screen.
  const { checked } = useStoredUser();
  useEffect(() => {
    if (!checked || !isNativeApp()) return;
    // One frame, so the first real screen has painted underneath.
    const frame = requestAnimationFrame(() => {
      void SplashScreen.hide({ fadeOutDuration: 200 }).catch(() => {});
    });
    return () => cancelAnimationFrame(frame);
  }, [checked]);

  useEffect(() => {
    if (!isNativeApp()) return;
    const root = document.documentElement;

    // NATIVE_SCRIPT does this before paint when the viewport tag is already
    // parsed; this catches the case where it came later in <head>.
    const viewport = document.querySelector('meta[name="viewport"]');
    const vp = viewport?.getAttribute("content") ?? "";
    if (viewport && !vp.includes("user-scalable")) {
      viewport.setAttribute("content", `${vp}, maximum-scale=1, user-scalable=no`);
    }

    // Light text on the dark theme, dark text on the light one.
    const syncStatusBar = () => {
      const dark = root.getAttribute("data-theme") === "dark";
      void StatusBar.setStyle({ style: dark ? Style.Dark : Style.Light }).catch(() => {});
    };
    syncStatusBar();
    const themeWatch = new MutationObserver(syncStatusBar);
    themeWatch.observe(root, { attributes: true, attributeFilter: ["data-theme"] });

    void Keyboard.setAccessoryBarVisible({ isVisible: false }).catch(() => {});

    const onPointerDown = (e: PointerEvent) => {
      const el = (e.target as Element | null)?.closest(TAPPABLE);
      if (el && !el.matches(":disabled, [aria-disabled='true']")) hapticTap();
    };
    document.addEventListener("pointerdown", onPointerDown, { passive: true });

    return () => {
      themeWatch.disconnect();
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  return null;
}
