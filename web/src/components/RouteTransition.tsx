"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useStoredUser } from "@/lib/auth";
import { isNativeApp } from "@/lib/native";
import { isImmersive } from "@/lib/routes";
import { PullIndicator, usePullToRefresh } from "./PullToRefresh";

interface Nav {
  /** Where you've been, most recent last. */
  stack: string[];
  /** "none": iOS's swipe-back already animated the way back, or a pull to
   * refresh is re-showing the same page — nothing should slide. */
  direction: "forward" | "back" | "none";
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
 * in the stack. In the iOS app the same pop comes from the edge swipe, which
 * animates itself, so that one doesn't slide again.
 *
 * Also where pull-to-refresh lives: the page is keyed on the refresh
 * generation, so a pull re-mounts it and it loads afresh.
 */
export default function RouteTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [nav, setNav] = useState<Nav>({ stack: [pathname], direction: "forward" });
  const { user } = useStoredUser();
  const { pull, generation } = usePullToRefresh(!!user && !isImmersive(pathname));
  const [shownGeneration, setShownGeneration] = useState(generation);

  // Where a history pop inside the app landed — there that means iOS's
  // swipe from the left edge (MainViewController in the iOS project), which
  // iOS has already animated.
  const [poppedTo, setPoppedTo] = useState<string | null>(null);
  useEffect(() => {
    if (!isNativeApp()) return;
    const onPop = () => setPoppedTo(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // Derived during render rather than in an effect: the animation starts on
  // the first frame after a navigation, and a direction settled afterwards
  // would play the wrong way and then visibly correct itself. Setting state
  // here is React's documented way to adjust state when an input changes —
  // it re-renders immediately, before anything is painted.
  if (nav.stack[nav.stack.length - 1] !== pathname) {
    const seen = nav.stack.lastIndexOf(pathname);
    const swiped = poppedTo === pathname;
    if (poppedTo !== null) setPoppedTo(null);
    setNav(
      seen === -1
        ? { stack: [...nav.stack, pathname], direction: "forward" }
        : { stack: nav.stack.slice(0, seen + 1), direction: swiped ? "none" : "back" },
    );
  } else if (generation !== shownGeneration) {
    setShownGeneration(generation);
    setNav({ ...nav, direction: "none" });
  }

  return (
    <>
      <PullIndicator pull={pull} />
      {/* Keying on the pathname restarts the animation on every navigation;
          without it React reuses the node and nothing moves. The refresh
          generation in the key is what makes a pull re-load the page. */}
      <div
        key={`${pathname}#${generation}`}
        data-testid="route-transition"
        data-direction={nav.direction}
        // Inherits body's column flex so `flex-1` on each page still fills
        // the viewport — without this the wrapper collapses to content height.
        className={`flex flex-1 flex-col ${
          nav.direction === "back" ? "route-back" : nav.direction === "forward" ? "route-forward" : ""
        }`}
      >
        {children}
      </div>
    </>
  );
}
