"use client";

import { useEffect, useRef, useState } from "react";
import { hapticCommit, isNativeApp } from "@/lib/native";

/** How far past the top you pull before letting go refreshes. */
const THRESHOLD = 80;
/** Long enough to read as "it did something" even when the data's instant. */
const SPIN_MS = 700;

type Pull = { phase: "idle" } | { phase: "pulling"; progress: number } | { phase: "refreshing" };

/**
 * Pull down from the top of a page to reload it, as in any iOS list. Only
 * in the app (a browser has its own reload) and only where `enabled`.
 *
 * Every page loads its own data when it mounts, so refreshing is
 * re-mounting: `generation` goes up and the caller keys the page on it.
 * The pull itself rides iOS's own rubber-band overscroll, so nothing here
 * moves the page — the indicator just reports how far it's gone.
 */
export function usePullToRefresh(enabled: boolean) {
  const [pull, setPull] = useState<Pull>({ phase: "idle" });
  const [generation, setGeneration] = useState(0);
  const start = useRef<number | null>(null);
  const armed = useRef(false);

  useEffect(() => {
    if (!enabled || !isNativeApp()) return;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const onStart = (e: TouchEvent) => {
      start.current = window.scrollY <= 0 && e.touches.length === 1 ? e.touches[0].clientY : null;
      armed.current = false;
    };
    const onMove = (e: TouchEvent) => {
      if (start.current === null) return;
      const dy = e.touches[0].clientY - start.current;
      if (dy <= 0 || window.scrollY > 0) {
        setPull({ phase: "idle" });
        return;
      }
      const progress = Math.min(dy / THRESHOLD, 1);
      // A bump the moment it's far enough, so you know letting go counts.
      if (progress === 1 && !armed.current) hapticCommit();
      armed.current = progress === 1;
      setPull({ phase: "pulling", progress });
    };
    const onEnd = () => {
      if (start.current === null) return;
      start.current = null;
      if (!armed.current) {
        setPull({ phase: "idle" });
        return;
      }
      armed.current = false;
      setPull({ phase: "refreshing" });
      setGeneration((g) => g + 1);
      timer = setTimeout(() => setPull({ phase: "idle" }), SPIN_MS);
    };

    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: true });
    document.addEventListener("touchend", onEnd);
    document.addEventListener("touchcancel", onEnd);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled]);

  return { pull, generation };
}

/** The circle under the top bar: an arrow that turns as you pull, then a
 * spinner while the page reloads. */
export function PullIndicator({ pull }: { pull: Pull }) {
  if (pull.phase === "idle") return null;
  const progress = pull.phase === "refreshing" ? 1 : pull.progress;
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 z-20 flex justify-center"
      style={{
        top: `calc(env(safe-area-inset-top) + 3.75rem)`,
        opacity: Math.min(progress * 1.4, 1),
      }}
    >
      <div className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-surface shadow-md">
        {pull.phase === "refreshing" ? (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
        ) : (
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            style={{ transform: `rotate(${progress * 180}deg)`, transition: "transform 80ms linear" }}
          >
            <path d="M12 5v14M6 13l6 6 6-6" stroke="var(--brand)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
    </div>
  );
}
