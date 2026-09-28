"use client";

import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

/** True when `next` is an older snapshot of the same room than `prev`.
 *
 * Room states carry a seq that only ever grows. A poll that set off just
 * before your own command landed can arrive just after its response — and
 * painting it would briefly undo what you did (a submitted card count
 * reappearing as an empty form). Anything without a seq is never stale. */
function isStale(prev: unknown, next: unknown): boolean {
  const p = prev as { seq?: unknown; room_id?: unknown } | null;
  const n = next as { seq?: unknown; room_id?: unknown } | null;
  return (
    typeof p?.seq === "number" &&
    typeof n?.seq === "number" &&
    p.room_id === n.room_id &&
    n.seq < p.seq
  );
}

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
  const [data, setDataRaw] = useState<T | null>(initial);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const setData = useCallback((action: SetStateAction<T | null>) => {
    setDataRaw((prev) => {
      const next =
        typeof action === "function"
          ? (action as (p: T | null) => T | null)(prev)
          : action;
      return isStale(prev, next) ? prev : next;
    });
  }, []);

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
