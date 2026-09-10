"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Polls `fetcher` on an interval while mounted. This stands in for Supabase
 * Realtime for now (see ADR-0003) — command endpoints already return fresh
 * state, so `setData` lets callers update immediately after their own
 * actions without waiting for the next tick.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
  /** Renders immediately from state the caller already has, instead of
   * blocking on the first tick — the room page knows the room's state the
   * moment it was created, and waiting a round trip to re-learn it is the
   * bulk of what makes opening a new room feel slow. */
  initial: T | null = null,
) {
  const [data, setData] = useState<T | null>(initial);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const result = await fetcherRef.current();
        if (!cancelled) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
      } finally {
        if (!cancelled) timer = setTimeout(tick, intervalMs);
      }
    }

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, setData };
}
