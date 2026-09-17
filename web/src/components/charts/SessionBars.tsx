"use client";

import type { SessionFact } from "@/lib/statsFactsTypes";
import { AXIS, ChartFrame, EmptyChart, NEG, POS, money, shortDate, useHovered } from "./Chart";

/** Per-session result as a diverging bar chart — the shape of your nights at
 * a glance: streaks, outliers, and whether the wins are many-and-small or
 * few-and-large, none of which the cumulative line shows. */
export default function SessionBars({
  sessions,
  onSelect,
}: {
  sessions: SessionFact[];
  onSelect?: (roomId: string) => void;
}) {
  const { hovered, bind, clear } = useHovered();
  if (sessions.length === 0) {
    return (
      <ChartFrame title="Session results" testId="chart-sessions">
        <EmptyChart text="No sessions in this range." />
      </ChartFrame>
    );
  }

  const W = 320;
  const H = 120;
  const PAD_Y = 10;
  const peak = Math.max(1, ...sessions.map((s) => Math.abs(s.net_cents)));
  const innerH = H - PAD_Y * 2;
  const midY = PAD_Y + innerH / 2;
  const slot = W / sessions.length;
  const barW = Math.max(2, Math.min(18, slot * 0.7));
  const active = hovered !== null ? sessions[hovered] : null;

  return (
    <ChartFrame
      title="Session results"
      hint="tap a bar"
      testId="chart-sessions"
      tooltip={
        active
          ? {
              x: ((hovered! + 0.5) * slot * 100) / W,
              y: (midY / H) * 100,
              content: (
                <>
                  <div
                    className={`font-semibold ${
                      active.net_cents < 0 ? "text-danger" : "text-brand-strong"
                    }`}
                  >
                    {money(active.net_cents)}
                  </div>
                  <div className="text-muted">
                    {shortDate(active.ended_at)} · {active.game_type}
                  </div>
                  {active.opponents.length > 0 && (
                    <div className="text-muted">
                      vs {active.opponents.map((o) => o.display_name).join(", ")}
                    </div>
                  )}
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
        aria-label={`Net result for each of ${sessions.length} sessions`}
        onPointerLeave={clear}
      >
        <line x1={0} y1={midY} x2={W} y2={midY} stroke={AXIS} strokeWidth={1} />
        {sessions.map((s, i) => {
          const h = (Math.abs(s.net_cents) / peak) * (innerH / 2);
          const up = s.net_cents >= 0;
          const x = i * slot + (slot - barW) / 2;
          return (
            <g key={s.room_id} {...bind(i)}>
              {/* Full-height transparent target so thin bars stay tappable. */}
              <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
              <rect
                x={x}
                y={up ? midY - h : midY}
                width={barW}
                height={Math.max(1, h)}
                rx={1}
                fill={up ? POS : NEG}
                opacity={hovered === null || hovered === i ? 1 : 0.45}
                style={{ cursor: onSelect ? "pointer" : "default" }}
                onClick={() => onSelect?.(s.room_id)}
              />
            </g>
          );
        })}
      </svg>
    </ChartFrame>
  );
}
