"use client";

import { Capacitor } from "@capacitor/core";
import { Haptics, ImpactStyle, NotificationType } from "@capacitor/haptics";

/** True inside the iOS app; false in a browser tab, including on a phone. */
export const isNativeApp = () => Capacitor.isNativePlatform();

// Haptics are fire-and-forget: a phone that can't buzz just doesn't, and
// that must never get in the way of the tap itself.
const quietly = (p: Promise<unknown>) => void p.catch(() => {});

/** The light tick every button gives (see NativeShell). */
export function hapticTap(): void {
  if (isNativeApp()) quietly(Haptics.impact({ style: ImpactStyle.Light }));
}

/** A firmer bump for a committed action: submitting a hand, YAO/GANG/HU. */
export function hapticCommit(): void {
  if (isNativeApp()) quietly(Haptics.impact({ style: ImpactStyle.Medium }));
}

/** Something went well — a game ended, a win. */
export function hapticSuccess(): void {
  if (isNativeApp()) quietly(Haptics.notification({ type: NotificationType.Success }));
}

/** Something was refused — a validation error, a failed request. */
export function hapticError(): void {
  if (isNativeApp()) quietly(Haptics.notification({ type: NotificationType.Error }));
}
