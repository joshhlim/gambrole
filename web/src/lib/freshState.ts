"use client";

/** Reads the just-created room state stashed by /new (see there), so the
 * room page can paint immediately instead of waiting a round trip to
 * re-learn what the create call already returned.
 *
 * Only trusted for a few seconds: past that we'd rather show a brief
 * "Loading…" than confidently render a room as it looked ages ago. */
const MAX_AGE_MS = 15_000;

export function readFreshState<T>(roomId: string): T | null {
  try {
    const raw = sessionStorage.getItem(`gambrole_state_${roomId}`);
    if (!raw) return null;
    const { at, state } = JSON.parse(raw) as { at: number; state: T };
    return Date.now() - at < MAX_AGE_MS ? state : null;
  } catch {
    return null;
  }
}
