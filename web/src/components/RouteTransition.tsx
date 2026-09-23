"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";

interface Nav {
  /** Where you've been, most recent last. */
  stack: string[];
  direction: "forward" | "back";
}

/**
 * Slides each page in from the direction you travelled.
 *
 * Direction comes from a stack of where you've been rather than from
 * comparing path depth: `/stats?player=…` back to `/friends` is a return
 * trip even though neither path contains the other, and depth alone calls
 * that wrong. If the incoming path is already somewhere in the stack we're
 * going back and unwind to it; otherwise it's somewhere new and gets pushed.
 *
 * Browser back/forward needs no special handling — it changes the pathname
 * like any other navigation, and the previous path is by definition already
 * in the stack.
 */
export default function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [nav, setNav] = useState<Nav>({ stack: [pathname], direction: "forward" });

  // Derived during render rather than in an effect: the animation starts on
  // the first frame after a navigation, and a direction settled afterwards
  // would play the wrong way and then visibly correct itself. Setting state
  // here is React's documented way to adjust state when an input changes —
  // it re-renders immediately, before anything is painted.
  if (nav.stack[nav.stack.length - 1] !== pathname) {
    const seen = nav.stack.lastIndexOf(pathname);
    setNav(
      seen === -1
        ? { stack: [...nav.stack, pathname], direction: "forward" }
        : { stack: nav.stack.slice(0, seen + 1), direction: "back" },
    );
  }

  return (
    // Keying on the pathname restarts the animation on every navigation;
    // without it React reuses the node and nothing moves.
    <div
      key={pathname}
      data-testid="route-transition"
      data-direction={nav.direction}
      // Inherits body's column flex so `flex-1` on each page still fills
      // the viewport — without this the wrapper collapses to content height.
      className={`flex flex-1 flex-col ${nav.direction === "back" ? "route-back" : "route-forward"}`}
    >
      {children}
    </div>
  );
}
