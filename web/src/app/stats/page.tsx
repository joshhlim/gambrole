"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { statsApi } from "@/lib/statsApi";
import type {
  MahjongPlayerStats,
  OverviewStats,
  SessionResult,
  StatsResponse,
  TaidiPlayerStats,
} from "@/lib/statsTypes";

type Tab = "overview" | "taidi" | "mahjong";

function dollars(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function StatTile({
  label,
  value,
  sub,
  valueClassName,
  testId,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClassName?: string;
  testId?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p data-testid={testId} className={`text-xl font-bold ${valueClassName ?? "text-foreground"}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-muted mt-0.5">{sub}</p>}
    </div>
  );
}

function BarRow({
  label,
  value,
  max,
  formatValue,
}: {
  label: string;
  value: number;
  max: number;
  formatValue: (v: number) => string;
}) {
  const width = max > 0 ? Math.max(4, (value / max) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-foreground">{label}</span>
        <span className="font-semibold text-brand-strong">{formatValue(value)}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-sm bg-border">
        <div className="h-full rounded-r-sm bg-brand-strong" style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <p data-testid="stats-empty" className="text-center text-sm text-muted py-8">
      {text}
    </p>
  );
}

/** Cumulative net result over time as a hand-rolled line+area chart — one
 * series, so no legend needed; colored by whether the running total ends
 * positive or negative, matching the app's existing profit/loss
 * convention (see MahjongRoom's standing amounts). */
function TrendChart({ trend }: { trend: SessionResult[] }) {
  if (trend.length === 0) return null;

  const width = 320;
  const height = 120;
  const pad = 14;
  const values = trend.map((s) => s.cumulative_cents);
  const rawMin = Math.min(0, ...values);
  const rawMax = Math.max(0, ...values);
  // A little headroom on both ends, so the zero reference line never sits
  // exactly on the chart's own edge (e.g. an all-negative trend would
  // otherwise put it right at the top, indistinguishable from the frame).
  const headroom = (rawMax - rawMin || 1) * 0.15;
  const min = rawMin - headroom;
  const max = rawMax + headroom;
  const range = max - min || 1;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const stepX = trend.length > 1 ? innerW / (trend.length - 1) : 0;
  const yFor = (v: number) => pad + innerH - ((v - min) / range) * innerH;
  const points = values.map((v, i) => [pad + i * stepX, yFor(v)] as const);
  const linePath = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const zeroY = yFor(0);
  const [lastX, lastY] = points[points.length - 1];
  const finalValue = values[values.length - 1];
  const color = finalValue < 0 ? "var(--danger)" : "var(--brand-strong)";
  const areaPath = `${linePath} L${lastX},${zeroY} L${points[0][0]},${zeroY} Z`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto"
      role="img"
      aria-label={`Cumulative result trend, ending at ${dollars(finalValue)}`}
    >
      <line
        x1={pad}
        y1={zeroY}
        x2={width - pad}
        y2={zeroY}
        stroke="var(--border)"
        strokeWidth={1}
      />
      <path d={areaPath} fill={color} fillOpacity={0.1} stroke="none" />
      <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={lastX} cy={lastY} r={4} fill={color} stroke="var(--surface)" strokeWidth={2} />
      <text
        x={lastX}
        y={lastY - 10 < 10 ? lastY + 18 : lastY - 10}
        textAnchor="end"
        fontSize={11}
        fontWeight={700}
        fill={color}
      >
        {dollars(finalValue)}
      </text>
    </svg>
  );
}

function OverviewTab({ overview }: { overview: OverviewStats }) {
  if (overview.total_sessions === 0) {
    return <EmptyState text="No finished games yet — play a room to see your stats here." />;
  }
  const streakCount = Math.abs(overview.current_streak);
  const streakNoun = overview.current_streak > 0 ? "win" : "loss";
  const streakLabel =
    overview.current_streak === 0
      ? "—"
      : `${streakCount} ${streakNoun}${streakCount === 1 ? "" : streakNoun === "win" ? "s" : "es"}`;

  return (
    <div className="space-y-6">
      <div className="text-center">
        <p className="text-xs uppercase tracking-widest text-muted mb-1">Total winnings</p>
        <p
          data-testid="overview-total"
          className={`text-4xl font-extrabold ${
            overview.total_cents < 0 ? "text-danger" : "text-brand-strong"
          }`}
        >
          {dollars(overview.total_cents)}
        </p>
      </div>

      <TrendChart trend={overview.trend} />

      <div className="grid grid-cols-2 gap-3">
        <StatTile
          testId="overview-taidi-cents"
          label="Taidi"
          value={dollars(overview.taidi_cents)}
          valueClassName={overview.taidi_cents < 0 ? "text-danger" : "text-brand-strong"}
          sub={`${overview.taidi_sessions} session${overview.taidi_sessions === 1 ? "" : "s"}`}
        />
        <StatTile
          testId="overview-mahjong-cents"
          label="Mahjong"
          value={dollars(overview.mahjong_cents)}
          valueClassName={overview.mahjong_cents < 0 ? "text-danger" : "text-brand-strong"}
          sub={`${overview.mahjong_chips} chips · ${overview.mahjong_sessions} session${
            overview.mahjong_sessions === 1 ? "" : "s"
          }`}
        />
        <StatTile label="Total sessions" value={String(overview.total_sessions)} />
        <StatTile testId="overview-streak" label="Current streak" value={streakLabel} />
        <StatTile
          label="Favorite game"
          value={overview.favorite_game ? capitalize(overview.favorite_game) : "—"}
        />
        <StatTile
          label="Last played"
          value={overview.last_played ? formatDate(overview.last_played) : "—"}
        />
      </div>
    </div>
  );
}

function TaidiTab({ stats }: { stats: TaidiPlayerStats | null }) {
  if (!stats) return <EmptyState text="No finished Taidi games yet." />;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3">
        <StatTile
          testId="taidi-round-win-rate"
          label="Round win rate"
          value={pct(stats.round_win_rate)}
          sub={`${stats.round_wins} of ${stats.rounds_played} rounds`}
        />
        <StatTile
          testId="taidi-profit-rate"
          label="Profit rate"
          value={pct(stats.profit_rate)}
          sub={`${stats.profit_rounds} of ${stats.rounds_played} rounds`}
        />
        <StatTile
          testId="taidi-double-rate"
          label="Double rate"
          value={pct(stats.double_rate)}
          sub={`${stats.double_rounds} of ${stats.payer_rounds} losing rounds`}
        />
        <StatTile
          testId="taidi-triple-rate"
          label="Triple rate"
          value={pct(stats.triple_rate)}
          sub={`${stats.triple_rounds} of ${stats.payer_rounds} losing rounds`}
        />
        <StatTile label="Special hands claimed" value={String(stats.special_hands_claimed)} />
        <StatTile
          label="Sessions won"
          value={`${stats.lifetime.wins} of ${stats.lifetime.games}`}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <StatTile
          label="Best round"
          value={stats.best_round_cents != null ? dollars(stats.best_round_cents) : "—"}
          valueClassName={
            stats.best_round_cents != null && stats.best_round_cents < 0
              ? "text-danger"
              : "text-brand-strong"
          }
        />
        <StatTile
          label="Worst round"
          value={stats.worst_round_cents != null ? dollars(stats.worst_round_cents) : "—"}
          valueClassName={
            stats.worst_round_cents != null && stats.worst_round_cents < 0
              ? "text-danger"
              : "text-brand-strong"
          }
        />
      </div>
    </div>
  );
}

const MAHJONG_KIND_LABELS: Record<string, string> = {
  yao: "咬 Yao",
  gang: "槓 Gang",
  hu: "胡 Hu",
  bao: "包 Bao",
  zimo_bonus: "Zimo bonus",
  klppdd: "KLPPDD",
};

function MahjongTab({ stats }: { stats: MahjongPlayerStats | null }) {
  if (!stats) return <EmptyState text="No finished Mahjong games yet." />;

  const modeEntries = (["direct", "zimo", "bao"] as const).filter(
    (m) => (stats.win_mode_counts[m] ?? 0) > 0,
  );
  const modeMax = Math.max(1, ...modeEntries.map((m) => stats.win_mode_counts[m] ?? 0));
  const taiEntries = Object.entries(stats.tai_distribution).sort(
    ([a], [b]) => Number(a) - Number(b),
  );
  const taiMax = Math.max(1, ...taiEntries.map(([, c]) => c));
  const kindEntries = Object.entries(stats.profit_by_kind);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3">
        <StatTile
          testId="mahjong-hu-rate"
          label="HU rate"
          value={pct(stats.hu_rate)}
          sub={`${stats.hu_count} of ${stats.hands_played} hands`}
        />
        <StatTile
          testId="mahjong-dealer-win-rate"
          label="Dealer win rate"
          value={pct(stats.dealer_win_rate)}
          sub={`${stats.dealer_wins} of ${stats.dealer_hands} dealer hands`}
        />
        <StatTile
          label="Average tai"
          value={stats.avg_tai_on_wins ? stats.avg_tai_on_wins.toFixed(1) : "—"}
        />
        <StatTile
          label="Sessions won"
          value={`${stats.lifetime.wins} of ${stats.lifetime.games}`}
        />
      </div>

      {modeEntries.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-widest text-muted mb-2">Win method</p>
          <div className="space-y-2">
            {modeEntries.map((m) => (
              <BarRow
                key={m}
                label={capitalize(m)}
                value={stats.win_mode_counts[m] ?? 0}
                max={modeMax}
                formatValue={(v) => String(v)}
              />
            ))}
          </div>
        </div>
      )}

      {taiEntries.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-widest text-muted mb-2">Tai distribution</p>
          <div className="space-y-2">
            {taiEntries.map(([tai, count]) => (
              <BarRow
                key={tai}
                label={`${tai} 台`}
                value={count}
                max={taiMax}
                formatValue={(v) => String(v)}
              />
            ))}
          </div>
        </div>
      )}

      {kindEntries.length > 0 && (
        <div>
          <p className="text-xs uppercase tracking-widest text-muted mb-2">Profit by action</p>
          <div className="space-y-2">
            {kindEntries.map(([kind, amount]) => (
              <div
                key={kind}
                className="flex items-center justify-between rounded-xl border border-border bg-surface px-4 py-2.5 text-sm"
              >
                <span className="font-medium">{MAHJONG_KIND_LABELS[kind] ?? kind}</span>
                <span className={`font-bold ${amount < 0 ? "text-danger" : "text-brand-strong"}`}>
                  {amount >= 0 ? "+" : ""}
                  {amount} chips
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <StatTile
          label="Best hand"
          value={stats.best_hand_chips != null ? `${stats.best_hand_chips} chips` : "—"}
          valueClassName={
            stats.best_hand_chips != null && stats.best_hand_chips < 0
              ? "text-danger"
              : "text-brand-strong"
          }
        />
        <StatTile
          label="Worst hand"
          value={stats.worst_hand_chips != null ? `${stats.worst_hand_chips} chips` : "—"}
          valueClassName={
            stats.worst_hand_chips != null && stats.worst_hand_chips < 0
              ? "text-danger"
              : "text-brand-strong"
          }
        />
      </div>
    </div>
  );
}

export default function StatsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [tab, setTab] = useState<Tab>("overview");
  const [data, setData] = useState<StatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // See the matching comment in room/[roomId]/page.tsx and new/page.tsx —
    // must wait for `checked`, or a genuinely signed-in user gets bounced
    // before the client-only auth read resolves.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    statsApi
      .getMine()
      .then(setData)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Couldn't load stats."));
  }, [user]);

  if (!user) return null;

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">My Stats</h1>
      </div>

      {error && (
        <p data-testid="stats-error" className="text-sm text-center text-danger mb-4">
          {error}
        </p>
      )}

      {!data ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-2">
            {(["overview", "taidi", "mahjong"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                data-testid={`stats-tab-${t}`}
                className={`rounded-xl border px-2 py-2 text-xs font-semibold capitalize ${
                  tab === t
                    ? "border-brand-strong bg-[#FFF8E1] text-brand"
                    : "border-border bg-surface text-muted"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "overview" && <OverviewTab overview={data.overview} />}
          {tab === "taidi" && <TaidiTab stats={data.taidi} />}
          {tab === "mahjong" && <MahjongTab stats={data.mahjong} />}
        </div>
      )}
    </main>
  );
}
