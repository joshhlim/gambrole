"use client";

import type { SessionFact } from "@/lib/statsFactsTypes";
import {
  AXIS,
  ChartFrame,
  EmptyChart,
  NEG,
  POS,
  money,
  moneyShort,
  shortDate,
  useHovered,
} from "./Chart";

/** Cumulative net over time. One series, so no legend — coloured by whether
 * you're up or down overall, matching the profit/loss convention used
 * everywhere else in the app. */
export default function TrendLine({
  points,
  onSelect,
}: {
  points: { session: SessionFact; total: number }[];
  onSelect?: (roomId: string) => void;
}) {
  const { hovered, bind, clear } = useHovered();
  if (points.length === 0) {
    return (
      <ChartFrame title="Cumulative result" testId="chart-trend">
        <EmptyChart text="No sessions in this range." />
      </ChartFrame>
    );
  }

  const W = 320;
  const H = 130;
  const PAD_X = 8;
  const PAD_Y = 16;
  const values = points.map((p) => p.total);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  // Headroom so the zero line never sits flush against the frame, where it
  // would be indistinguishable from the border.
  const pad = (rawMax - rawMin || 100) * 0.15;
  const min = rawMin - pad;
  const max = rawMax + pad;
  const innerW = W - PAD_X * 2;
  const innerH = H - PAD_Y * 2;
  const stepX = points.length > 1 ? innerW / (points.length - 1) : 0;
  const xFor = (i: number) => PAD_X + (points.length > 1 ? i * stepX : innerW / 2);
  const yFor = (v: number) => PAD_Y + innerH - ((v - min) / (max - min || 1)) * innerH;

  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${xFor(i)},${yFor(p.total)}`).join(" ");
  const zeroY = yFor(0);
  const final = values[values.length - 1];
  const color = final < 0 ? NEG : POS;
  const area = `${line} L${xFor(points.length - 1)},${zeroY} L${xFor(0)},${zeroY} Z`;
  const active = hovered !== null ? points[hovered] : null;

  return (
    <ChartFrame
      title="Cumulative result"
      hint={`${points.length} session${points.length === 1 ? "" : "s"}`}
      testId="chart-trend"
      tooltip={
        active
          ? {
              x: (xFor(hovered!) / W) * 100,
              y: (yFor(active.total) / H) * 100,
              content: (
                <>
                  <div className="font-semibold">{money(active.total)}</div>
                  <div className="text-muted">
                    {shortDate(active.session.ended_at)} · {money(active.session.net_cents)} this
                    session
                  </div>
                </>
              ),
            }
          : null
      }
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full touch-none"
        role="img"
        aria-label={`Cumulative result over ${points.length} sessions, ending at ${money(final)}`}
        onPointerLeave={clear}
      >
        <line x1={PAD_X} y1={zeroY} x2={W - PAD_X} y2={zeroY} stroke={AXIS} strokeWidth={1} />
        <path d={area} fill={color} fillOpacity={0.1} />
        <path
          d={line}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {active && (
          <line
            x1={xFor(hovered!)}
            y1={PAD_Y}
            x2={xFor(hovered!)}
            y2={H - PAD_Y}
            stroke={AXIS}
            strokeWidth={1}
          />
        )}
        <circle
          cx={xFor(points.length - 1)}
          cy={yFor(final)}
          r={3.5}
          fill={color}
          stroke="var(--surface)"
          strokeWidth={2}
        />
        {active && (
          <circle
            cx={xFor(hovered!)}
            cy={yFor(active.total)}
            r={4}
            fill={color}
            stroke="var(--surface)"
            strokeWidth={2}
          />
        )}
        {/* Invisible full-height hit targets: a 2px line is impossible to
            hit with a finger, so each point owns a column instead. */}
        {points.map((p, i) => (
          <rect
            key={p.session.room_id}
            x={xFor(i) - (stepX || innerW) / 2}
            y={0}
            width={stepX || innerW}
            height={H}
            fill="transparent"
            style={{ cursor: onSelect ? "pointer" : "default" }}
            onClick={() => onSelect?.(p.session.room_id)}
            {...bind(i)}
          />
        ))}
        {/* Top of the axis is the highest the running total ever got —
            labelling it with the minimum would read as a ceiling. */}
        <text x={PAD_X} y={10} fontSize={9} fill="var(--muted)">
          peak {moneyShort(rawMax)}
        </text>
        <text x={PAD_X} y={H - 3} fontSize={9} fill="var(--muted)">
          low {moneyShort(rawMin)}
        </text>
        <text x={W - PAD_X} y={10} fontSize={9} fill={color} fontWeight={700} textAnchor="end">
          {money(final)}
        </text>
      </svg>
    </ChartFrame>
  );
}
