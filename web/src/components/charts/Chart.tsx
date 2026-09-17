"use client";

// A small hand-rolled chart toolkit. No library: the app is phone-first and
// these are simple enough that ~100KB of dependency would cost more than it
// saves. Interaction is deliberately pointer-based (not hover-only) so the
// same code works under a finger and a mouse.

import { useState, type ReactNode } from "react";

export const AXIS = "var(--border)";
export const POS = "var(--brand-strong)";
export const NEG = "var(--danger)";

/** Categorical fills for splits (win modes, multipliers). Ordered so the
 * first is the "good"/most common case and later ones read as escalation. */
export const SERIES = ["var(--brand-strong)", "var(--gold)", "var(--danger)", "var(--muted)"];

export function moneyShort(cents: number): string {
  const abs = Math.abs(cents) / 100;
  const sign = cents < 0 ? "-" : "";
  return abs >= 1000 ? `${sign}$${(abs / 1000).toFixed(1)}k` : `${sign}$${abs.toFixed(0)}`;
}

export function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

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
 * spread onto each hit target. */
export function useHovered() {
  const [hovered, setHovered] = useState<number | null>(null);
  const bind = (i: number) => ({
    onPointerEnter: () => setHovered(i),
    onPointerDown: () => setHovered(i),
    onPointerLeave: () => setHovered((cur) => (cur === i ? null : cur)),
  });
  return { hovered, bind, clear: () => setHovered(null) };
}
