"use client";

import { useCallback, useEffect, useRef, useState, type SetStateAction } from "react";

/** True when `next` is no newer a snapshot of the same room than `prev`.
 *
 * Room states carry a seq that only ever grows. A poll that set off just
 * before your own command landed can arrive just after its response — and
 * painting it would briefly undo what you did (a submitted card count
 * reappearing as an empty form). An equal seq is the same state again, and
 * keeping `prev` spares the whole room a re-render every tick. Anything
 * without a seq is never stale. */
function isStale(prev: unknown, next: unknown): boolean {
  const p = prev as { seq?: unknown; room_id?: unknown } | null;
  const n = next as { seq?: unknown; room_id?: unknown } | null;
  return (
    typeof p?.seq === "number" &&
    typeof n?.seq === "number" &&
    p.room_id === n.room_id &&
    n.seq <= p.seq
  );
}

const MAX_BACKOFF_MS = 15_000;

export interface PollingOptions<T> {
  intervalMs: number;
  /** Restart polling from scratch when any of these change. */
  deps?: unknown[];
  /** Renders immediately from state the caller already has, instead of
   * blocking on the first tick — the room page knows the room's state the
   * moment it was created, and waiting a round trip to re-learn it is the
   * bulk of what makes opening a new room feel slow. */
  initial?: T | null;
  /** False holds off polling entirely (e.g. until we know who's signed in,
   * so the first request doesn't go out without a token and fail). */
  enabled?: boolean;
  /** Errors that retrying can't fix (the room is gone, you're not allowed
   * in). Polling stops on one rather than hammering the server. */
  isFatal?: (e: Error) => boolean;
}

/**
 * Polls `fetcher` on an interval while mounted. This stands in for Supabase
 * Realtime for now (see ADR-0003) — command endpoints already return fresh
 * state, so `setData` lets callers update immediately after their own
 * actions without waiting for the next tick.
 *
 * Errors back off exponentially (capped), and nothing is fetched while the
 * tab is hidden — a phone face-down on the table shouldn't keep the radio
 * busy — with an immediate poll on coming back.
 */
export function usePolling<T>(fetcher: () => Promise<T>, options: PollingOptions<T>) {
  const { intervalMs, deps = [], initial = null, enabled = true } = options;
  const [data, setDataRaw] = useState<T | null>(initial);
  const [error, setError] = useState<Error | null>(null);
  const fetcherRef = useRef(fetcher);
  const isFatalRef = useRef(options.isFatal);
  useEffect(() => {
    fetcherRef.current = fetcher;
    isFatalRef.current = options.isFatal;
  });
  // Bumped whenever the caller writes data itself. A poll that set off
  // before that write carries an answer from before it, so it's dropped —
  // the seq guard covers rooms, this covers data without one (debts).
  const writes = useRef(0);
  const kick = useRef<() => void>(() => {});

  const setData = useCallback((action: SetStateAction<T | null>) => {
    writes.current++;
    setDataRaw((prev) => {
      const next =
        typeof action === "function"
          ? (action as (p: T | null) => T | null)(prev)
          : action;
      return isStale(prev, next) ? prev : next;
    });
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let inFlight = false;
    let failures = 0;
    let stopped = false;
    // A refresh asked for mid-poll: that poll may predate the change the
    // refresh is about, so go again as soon as it lands.
    let again = false;

    function schedule(ms: number) {
      clearTimeout(timer);
      if (!cancelled && !stopped && !document.hidden) timer = setTimeout(tick, ms);
    }

    async function tick() {
      if (inFlight || cancelled || stopped) return;
      inFlight = true;
      const startedAt = writes.current;
      try {
        const result = await fetcherRef.current();
        if (cancelled) return;
        failures = 0;
        setError(null);
        if (startedAt === writes.current) {
          setDataRaw((prev) => (isStale(prev, result) ? prev : result));
        }
      } catch (e) {
        if (cancelled) return;
        const err = e instanceof Error ? e : new Error(String(e));
        failures++;
        setError(err);
        if (isFatalRef.current?.(err)) stopped = true;
      } finally {
        inFlight = false;
        schedule(
          again
            ? 0
            : failures === 0
              ? intervalMs
              : Math.min(intervalMs * 2 ** failures, MAX_BACKOFF_MS),
        );
        again = false;
      }
    }

    kick.current = () => {
      if (inFlight) {
        again = true;
        return;
      }
      clearTimeout(timer);
      void tick();
    };

    function onVisibility() {
      if (document.hidden) clearTimeout(timer);
      else void tick();
    }

    void tick();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      kick.current = () => {};
      document.removeEventListener("visibilitychange", onVisibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs, ...deps]);

  /** Poll now instead of waiting for the next tick — e.g. right after an
   * action whose response only covers part of what's on screen. */
  const refresh = useCallback(() => kick.current(), []);

  return { data, error, setData, refresh };
}
