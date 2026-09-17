"use client";

import { ChartFrame, EmptyChart, SERIES, useHovered } from "./Chart";

export interface Slice {
  label: string;
  value: number;
}

/** A donut for a small categorical split (how your wins came about, how your
 * losing rounds were multiplied). Donut rather than pie so the total can sit
 * in the middle, which is the number people actually want alongside the
 * proportions. */
export default function SplitDonut({
  title,
  slices,
  centerLabel,
  testId,
}: {
  title: string;
  slices: Slice[];
  centerLabel?: string;
  testId?: string;
}) {
  const { hovered, bind, clear } = useHovered();
  const shown = slices.filter((s) => s.value > 0);
  const total = shown.reduce((a, s) => a + s.value, 0);
  if (total === 0) {
    return (
      <ChartFrame title={title} testId={testId}>
        <EmptyChart text="Nothing recorded yet." />
      </ChartFrame>
    );
  }

  const SIZE = 120;
  const R = 46;
  const STROKE = 18;
  const C = 2 * Math.PI * R;
  const arcs = shown.map((s, i) => {
    const frac = s.value / total;
    // Where this arc starts: everything before it. A running mutable total
    // would be cheaper, but there are at most four slices and this stays a
    // pure expression.
    const before = shown.slice(0, i).reduce((a, x) => a + x.value, 0) / total;
    return { ...s, frac, dash: frac * C, offset: before * C, color: SERIES[i % SERIES.length] };
  });
  const active = hovered !== null ? arcs[hovered] : null;

  return (
    <ChartFrame title={title} testId={testId}>
      <div className="flex items-center gap-3" onPointerLeave={clear}>
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="h-28 w-28 shrink-0 touch-none" role="img">
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            {arcs.map((a, i) => (
              <circle
                key={a.label}
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={R}
                fill="none"
                stroke={a.color}
                strokeWidth={hovered === i ? STROKE + 4 : STROKE}
                strokeDasharray={`${a.dash} ${C - a.dash}`}
                strokeDashoffset={-a.offset}
                opacity={hovered === null || hovered === i ? 1 : 0.45}
                {...bind(i)}
              />
            ))}
          </g>
          <text
            x={SIZE / 2}
            y={SIZE / 2 - 2}
            textAnchor="middle"
            fontSize={16}
            fontWeight={800}
            fill="var(--foreground)"
          >
            {active ? `${Math.round(active.frac * 100)}%` : total}
          </text>
          <text
            x={SIZE / 2}
            y={SIZE / 2 + 12}
            textAnchor="middle"
            fontSize={8}
            fill="var(--muted)"
          >
            {active ? active.label : (centerLabel ?? "total")}
          </text>
        </svg>
        <div className="min-w-0 flex-1 space-y-1">
          {arcs.map((a, i) => (
            <div
              key={a.label}
              className="flex items-center gap-2 text-[11px]"
              {...bind(i)}
              style={{ opacity: hovered === null || hovered === i ? 1 : 0.5 }}
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: a.color }}
                aria-hidden
              />
              <span className="flex-1 truncate text-foreground">{a.label}</span>
              <span className="font-semibold text-muted">
                {a.value} · {Math.round(a.frac * 100)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </ChartFrame>
  );
}
