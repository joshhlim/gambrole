"use client";

import { useState } from "react";

interface Seen<T> {
  key: T;
  direction: "forward" | "back";
}

/**
 * Slides tab content in from the side it came from, the same way whole
 * pages do — so moving between Overview and Taidi feels like the same
 * gesture as moving between screens.
 *
 * Direction comes from the tab's position in `order`: moving rightwards
 * along the tab bar slides in from the right, leftwards from the left,
 * which matches where the tab you tapped sits on screen.
 */
export default function TabTransition<T extends string>({
  tabKey,
  order,
  children,
}: {
  tabKey: T;
  /** The tabs left-to-right as they appear in the bar. */
  order: readonly T[];
  children: React.ReactNode;
}) {
  const [seen, setSeen] = useState<Seen<T>>({ key: tabKey, direction: "forward" });

  // Worked out during render for the same reason RouteTransition does it:
  // the animation starts on the first frame after the switch, so deciding
  // afterwards would play the wrong way and visibly correct itself.
  if (seen.key !== tabKey) {
    const from = order.indexOf(seen.key);
    const to = order.indexOf(tabKey);
    setSeen({ key: tabKey, direction: to >= from ? "forward" : "back" });
  }

  return (
    // Keyed so React swaps the node and the animation restarts; without it
    // the content changes in place and nothing moves.
    <div
      key={tabKey}
      data-testid="tab-transition"
      data-direction={seen.direction}
      className={seen.direction === "back" ? "route-back" : "route-forward"}
    >
      {children}
    </div>
  );
}
