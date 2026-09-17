"use client";

import type { OpponentRef } from "@/lib/statsFactsTypes";
import { ChartFrame, EmptyChart, NEG, POS, money, useHovered } from "./Chart";

export interface OpponentRow {
  opponent: OpponentRef;
  sessions: number;
  netCents: number;
}

/** How you do at the table when each person is there.
 *
 * Deliberately NOT billed as head-to-head: with three or four players the
 * event log can't attribute your night's result to one opponent, so this is
 * "your net across games they were in". Tapping one filters everything to
 * those games, which is where the real comparison happens. */
export default function OpponentBars({
  rows,
  selected,
  onToggle,
}: {
  rows: OpponentRow[];
  selected: string[];
  onToggle?: (playerId: string) => void;
}) {
  const { hovered, bind, clear } = useHovered();
  if (rows.length === 0) {
    return (
      <ChartFrame title="Who you play with" testId="chart-opponents">
        <EmptyChart text="No opponents in this range." />
      </ChartFrame>
    );
  }

  const peak = Math.max(1, ...rows.map((r) => Math.abs(r.netCents)));
  const active = hovered !== null ? rows[hovered] : null;

  return (
    <ChartFrame
      title="Who you play with"
      hint="tap to filter"
      testId="chart-opponents"
      tooltip={
        active
          ? {
              x: 50,
              y: 0,
              content: (
                <>
                  <div className="font-semibold">{active.opponent.display_name}</div>
                  <div className="text-muted">
                    {active.sessions} session{active.sessions === 1 ? "" : "s"} ·{" "}
                    {money(active.netCents)} for you
                  </div>
                </>
              ),
            }
          : null
      }
    >
      <div className="space-y-1.5" onPointerLeave={clear}>
        {rows.map((r, i) => {
          const pct = (Math.abs(r.netCents) / peak) * 50; // half-width each side
          const up = r.netCents >= 0;
          const isSel = selected.includes(r.opponent.player_id);
          return (
            <button
              key={r.opponent.player_id}
              type="button"
              data-testid={`opponent-row-${r.opponent.player_id}`}
              onClick={() => onToggle?.(r.opponent.player_id)}
              className={`block w-full rounded-lg px-1.5 py-1 text-left ${
                isSel ? "bg-[#FFF8E1]" : ""
              }`}
              {...bind(i)}
            >
              <div className="flex items-baseline justify-between text-[11px]">
                <span className={`font-medium ${isSel ? "text-brand" : "text-foreground"}`}>
                  {r.opponent.display_name}
                </span>
                <span className={`font-semibold ${up ? "text-brand-strong" : "text-danger"}`}>
                  {money(r.netCents)}
                </span>
              </div>
              {/* Diverging from a centre line, so losses read as losses
                  rather than as short wins. */}
              <div className="relative mt-0.5 h-2 w-full rounded-sm bg-border/50">
                <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <div
                  className="absolute inset-y-0 rounded-sm"
                  style={{
                    background: up ? POS : NEG,
                    left: up ? "50%" : `${50 - pct}%`,
                    width: `${Math.max(1, pct)}%`,
                    opacity: hovered === null || hovered === i ? 1 : 0.45,
                  }}
                />
              </div>
            </button>
          );
        })}
      </div>
    </ChartFrame>
  );
}
