"use client";

// A small hand-rolled chart toolkit. No library: the app is phone-first and
// these are simple enough that ~100KB of dependency would cost more than it
// saves. Interaction is deliberately pointer-based (not hover-only) so the
// same code works under a finger and a mouse.

import { useRef, useState, type PointerEvent, type ReactNode } from "react";

export const AXIS = "var(--border)";
export const POS = "var(--brand-strong)";
export const NEG = "var(--danger)";

/** Categorical fills for splits (win modes, multipliers). Ordered so the
 * first is the "good"/most common case and later ones read as escalation. */
export const SERIES = ["var(--brand-strong)", "var(--gold)", "var(--danger)", "var(--muted)"];

export { money, moneyShort } from "@/lib/format";

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Wraps a chart with a title and an overlay layer for tooltips. The tooltip
 * is HTML rather than SVG text so it can wrap, sit above everything, and
 * stay legible without manual glyph measuring. */
export function ChartFrame({
  title,
  hint,
  tooltip,
  children,
  testId,
}: {
  title: string;
  hint?: string;
  tooltip?: { x: number; y: number; content: ReactNode } | null;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <div data-testid={testId} className="rounded-xl border border-border bg-surface px-3 py-3">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-widest text-muted">{title}</p>
        {hint && <p className="text-[10px] text-muted">{hint}</p>}
      </div>
      <div className="relative">
        {children}
        {tooltip && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-lg border border-border bg-background px-2 py-1 text-[11px] leading-tight shadow-sm"
            style={{ left: `${tooltip.x}%`, top: `${tooltip.y}%` }}
          >
            {tooltip.content}
          </div>
        )}
      </div>
    </div>
  );
}

export function EmptyChart({ text }: { text: string }) {
  return <p className="py-6 text-center text-xs text-muted">{text}</p>;
}

/** Tracks which datum the pointer is over. Returns the index plus handlers to
 * spread onto each hit target.
 *
 * Touch has no hover, so a finger's tooltip stays up after it lifts (a
 * touch pointer "leaves" the moment it's raised, which used to wipe the
 * tooltip before it could be read). `activate` makes tappable charts
 * two-step on touch: the first tap shows the tooltip, a second tap on the
 * same point follows it. A mouse already saw the tooltip on hover, so its
 * click goes straight through. */
export function useHovered() {
  const [hovered, setHovered] = useState<number | null>(null);
  const pointer = useRef<string>("mouse");
  const armed = useRef<number | null>(null);
  const bind = (i: number) => ({
    onPointerEnter: (e: PointerEvent<Element>) => {
      if (e.pointerType !== "touch") setHovered(i);
    },
    onPointerDown: (e: PointerEvent<Element>) => {
      pointer.current = e.pointerType;
      armed.current = hovered === i ? i : null;
      setHovered(i);
    },
    onPointerLeave: (e: PointerEvent<Element>) => {
      if (e.pointerType !== "touch") setHovered((cur) => (cur === i ? null : cur));
    },
  });
  const clear = (e: PointerEvent<Element>) => {
    if (e.pointerType !== "touch") setHovered(null);
  };
  const activate = (i: number, go: () => void) => {
    if (pointer.current !== "touch" || armed.current === i) go();
  };
  return { hovered, bind, clear, activate };
}
