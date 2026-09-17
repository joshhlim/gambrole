"use client";

import type { SessionFact } from "@/lib/statsFactsTypes";
import { AXIS, ChartFrame, EmptyChart, NEG, POS, money, shortDate, useHovered } from "./Chart";

/** Does a longer night treat you better?
 *
 * Each dot is a session: how many rounds/hands were played against what you
 * walked away with. If short nights cluster below the line and long ones
 * above, variance is flattering you early and the edge shows up over time —
 * or the reverse, which is worth knowing before agreeing to "one more". */
export default function ResultScatter({ sessions }: { sessions: SessionFact[] }) {
  const { hovered, bind, clear } = useHovered();
  const points = sessions
    .map((s) => ({
      s,
      rounds: s.taidi?.rounds_played ?? s.mahjong?.hands_played ?? 0,
    }))
    .filter((p) => p.rounds > 0);

  if (points.length < 2) {
    return (
      <ChartFrame title="Session length vs result" testId="chart-scatter">
        <EmptyChart text="Needs at least two finished sessions." />
      </ChartFrame>
    );
  }

  const W = 320;
  const H = 140;
  const PAD = 18;
  const maxRounds = Math.max(...points.map((p) => p.rounds));
  const peak = Math.max(1, ...points.map((p) => Math.abs(p.s.net_cents)));
  const innerW = W - PAD * 2;
  const innerH = H - PAD * 2;
  const midY = PAD + innerH / 2;
  const xFor = (r: number) => PAD + (r / maxRounds) * innerW;
  const yFor = (c: number) => midY - (c / peak) * (innerH / 2);
  const active = hovered !== null ? points[hovered] : null;

  return (
    <ChartFrame
      title="Session length vs result"
      hint={`${points.length} sessions`}
      testId="chart-scatter"
      tooltip={
        active
          ? {
              x: (xFor(active.rounds) / W) * 100,
              y: (yFor(active.s.net_cents) / H) * 100,
              content: (
                <>
                  <div
                    className={`font-semibold ${
                      active.s.net_cents < 0 ? "text-danger" : "text-brand-strong"
                    }`}
                  >
                    {money(active.s.net_cents)}
                  </div>
                  <div className="text-muted">
                    {active.rounds} {active.s.game_type === "mahjong" ? "hands" : "rounds"} ·{" "}
                    {shortDate(active.s.ended_at)}
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
        aria-label="Each session's net result plotted against how many rounds were played"
        onPointerLeave={clear}
      >
        <line x1={PAD} y1={midY} x2={W - PAD} y2={midY} stroke={AXIS} strokeWidth={1} />
        {points.map((p, i) => (
          <circle
            key={p.s.room_id}
            cx={xFor(p.rounds)}
            cy={yFor(p.s.net_cents)}
            r={hovered === i ? 6 : 4}
            fill={p.s.net_cents >= 0 ? POS : NEG}
            fillOpacity={hovered === null || hovered === i ? 0.75 : 0.3}
            stroke="var(--surface)"
            strokeWidth={1}
            {...bind(i)}
          />
        ))}
        <text x={PAD} y={H - 4} fontSize={9} fill="var(--muted)">
          shorter
        </text>
        <text x={W - PAD} y={H - 4} fontSize={9} fill="var(--muted)" textAnchor="end">
          longer ({maxRounds})
        </text>
      </svg>
    </ChartFrame>
  );
}
