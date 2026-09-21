"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError, request } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import type { SessionFact, StatsFactsResponse } from "@/lib/statsFactsTypes";
import {
  applyFilters,
  bestWorstGame,
  cumulative,
  filtersActive,
  NO_FILTERS,
  opponentTally,
  rate,
  totals,
  type Filters,
  type Totals,
} from "@/lib/statsMath";
import { money } from "@/components/charts/Chart";
import TrendLine from "@/components/charts/TrendLine";
import SessionBars from "@/components/charts/SessionBars";
import OpponentBars from "@/components/charts/OpponentBars";
import SplitDonut from "@/components/charts/SplitDonut";
import ResultScatter from "@/components/charts/ResultScatter";

type Tab = "overview" | "taidi" | "mahjong";

function pct(r: number | null): string {
  return r === null ? "—" : `${Math.round(r * 100)}%`;
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Tile({
  label,
  value,
  sub,
  tone,
  testId,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "pos" | "neg";
  testId?: string;
}) {
  const toneClass =
    tone === "pos" ? "text-brand-strong" : tone === "neg" ? "text-danger" : "text-foreground";
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2.5">
      <p className="mb-0.5 text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p data-testid={testId} className={`text-lg font-bold ${toneClass}`}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-[10px] text-muted">{sub}</p>}
    </div>
  );
}

const DAY_PRESETS: { label: string; days: number | null }[] = [
  { label: "All time", days: null },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
  { label: "1y", days: 365 },
];
const COUNT_PRESETS: { label: string; lastN: number | null }[] = [
  { label: "All", lastN: null },
  { label: "10", lastN: 10 },
  { label: "25", lastN: 25 },
  { label: "50", lastN: 50 },
];

function FilterBar({
  filters,
  setFilters,
  shown,
  total,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  shown: number;
  total: number;
}) {
  const chip = (on: boolean) =>
    `rounded-lg border px-2 py-1 text-[11px] font-semibold ${
      on ? "border-brand-strong bg-[#FFF8E1] text-brand" : "border-border bg-surface text-muted"
    }`;
  return (
    <div className="space-y-2 rounded-xl border border-border bg-surface px-3 py-2.5">
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider text-muted">Filter</p>
        <div className="flex items-center gap-2">
          <span data-testid="filter-count" className="text-[10px] text-muted">
            {shown} of {total} sessions
          </span>
          {filtersActive(filters) && (
            <button
              type="button"
              onClick={() => setFilters(NO_FILTERS)}
              data-testid="filter-clear"
              className="text-[10px] font-semibold text-brand-strong"
            >
              Clear
            </button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {DAY_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            data-testid={`filter-days-${p.days ?? "all"}`}
            onClick={() => setFilters({ ...filters, days: p.days })}
            className={chip(filters.days === p.days)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] text-muted">Last</span>
        {COUNT_PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            data-testid={`filter-last-${p.lastN ?? "all"}`}
            onClick={() => setFilters({ ...filters, lastN: p.lastN })}
            className={chip(filters.lastN === p.lastN)}
          >
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function OverviewTab({
  sessions,
  t,
  filters,
  setFilters,
  onSelectRoom,
}: {
  sessions: SessionFact[];
  t: Totals;
  filters: Filters;
  setFilters: (f: Filters) => void;
  onSelectRoom?: (roomId: string) => void;
}) {
  const opponents = useMemo(() => opponentTally(sessions), [sessions]);
  const mostPlayedWith = opponents[0];
  const bw = bestWorstGame(t);
  const mostPlayedGame =
    t.byGame.taidi.sessions === t.byGame.mahjong.sessions
      ? t.sessions === 0
        ? null
        : "tied"
      : t.byGame.taidi.sessions > t.byGame.mahjong.sessions
        ? "taidi"
        : "mahjong";

  return (
    <div className="space-y-4">
      <div className="text-center">
        <p className="mb-1 text-[10px] uppercase tracking-widest text-muted">Overall</p>
        <p
          data-testid="overview-total"
          className={`text-4xl font-extrabold ${
            t.netCents < 0 ? "text-danger" : "text-brand-strong"
          }`}
        >
          {money(t.netCents)}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Tile label="Sessions played" value={String(t.sessions)} testId="overview-sessions" />
        <Tile
          label="Most played with"
          value={mostPlayedWith?.opponent.display_name ?? "—"}
          sub={mostPlayedWith ? `${mostPlayedWith.sessions} sessions` : undefined}
          testId="overview-most-played-with"
        />
        <Tile
          label="Best game"
          value={bw ? capitalize(bw.best) : "—"}
          sub={bw ? money(t.byGame[bw.best].netCents) : "needs both games"}
          tone={bw && t.byGame[bw.best].netCents >= 0 ? "pos" : undefined}
          testId="overview-best-game"
        />
        <Tile
          label="Worst game"
          value={bw ? capitalize(bw.worst) : "—"}
          sub={bw ? money(t.byGame[bw.worst].netCents) : "needs both games"}
          tone={bw && t.byGame[bw.worst].netCents < 0 ? "neg" : undefined}
          testId="overview-worst-game"
        />
        <Tile
          label="Most played game"
          value={mostPlayedGame ? capitalize(mostPlayedGame) : "—"}
          sub={`${t.byGame.taidi.sessions} taidi · ${t.byGame.mahjong.sessions} mahjong`}
          testId="overview-most-played-game"
        />
        <Tile
          label="Avg per session"
          value={t.sessions ? money(Math.round(t.netCents / t.sessions)) : "—"}
          tone={t.netCents < 0 ? "neg" : "pos"}
        />
      </div>

      <TrendLine points={cumulative(sessions)} onSelect={onSelectRoom} />
      <SessionBars sessions={sessions} onSelect={onSelectRoom} />
      <OpponentBars
        rows={opponents}
        selected={filters.withPlayers}
        onToggle={(id) =>
          setFilters({
            ...filters,
            withPlayers: filters.withPlayers.includes(id)
              ? filters.withPlayers.filter((p) => p !== id)
              : [...filters.withPlayers, id],
          })
        }
      />
      <ResultScatter sessions={sessions} />
    </div>
  );
}

function TaidiTab({ sessions, t }: { sessions: SessionFact[]; t: Totals }) {
  if (t.byGame.taidi.sessions === 0) {
    return <p className="py-8 text-center text-sm text-muted">No Taidi sessions in this range.</p>;
  }
  const normalRounds = t.payerRounds - t.doubleRounds - t.tripleRounds;
  return (
    <div className="space-y-4">
      <div className="text-center">
        <p className="mb-1 text-[10px] uppercase tracking-widest text-muted">Taidi profit</p>
        <p
          data-testid="taidi-total"
          className={`text-3xl font-extrabold ${
            t.byGame.taidi.netCents < 0 ? "text-danger" : "text-brand-strong"
          }`}
        >
          {money(t.byGame.taidi.netCents)}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Tile label="Sessions played" value={String(t.byGame.taidi.sessions)} />
        <Tile
          label="Round win rate"
          value={pct(rate(t.roundsWon, t.roundsPlayed))}
          sub={`${t.roundsWon} of ${t.roundsPlayed}`}
          testId="taidi-round-win-rate"
        />
        <Tile
          label="Profit rate"
          value={pct(rate(t.profitRounds, t.roundsPlayed))}
          sub={`${t.profitRounds} rounds up`}
          testId="taidi-profit-rate"
        />
        <Tile
          label="Trapping rate"
          value={pct(rate(t.trappingWins, t.roundsWon))}
          sub={`${t.trappingWins} of ${t.roundsWon} wins caught someone`}
          testId="taidi-trapping-rate"
        />
        <Tile
          label="Double rate"
          value={pct(rate(t.doubleRounds, t.payerRounds))}
          sub={`${t.doubleRounds} of ${t.payerRounds} losing rounds`}
          testId="taidi-double-rate"
        />
        <Tile
          label="Triple rate"
          value={pct(rate(t.tripleRounds, t.payerRounds))}
          sub={`${t.tripleRounds} of ${t.payerRounds} losing rounds`}
          testId="taidi-triple-rate"
        />
        <Tile
          label="Special hand rate"
          value={pct(rate(t.specialHands, t.roundsPlayed))}
          sub={`${t.specialHands} claimed`}
          testId="taidi-special-rate"
        />
        <Tile label="Rounds played" value={String(t.roundsPlayed)} />
      </div>

      <SplitDonut
        title="How your losing rounds go"
        centerLabel="losing rounds"
        testId="chart-taidi-multipliers"
        slices={[
          { label: "Normal", value: Math.max(0, normalRounds) },
          { label: "Doubled", value: t.doubleRounds },
          { label: "Tripled", value: t.tripleRounds },
        ]}
      />
      <TrendLine points={cumulative(sessions)} />
    </div>
  );
}

function MahjongTab({ sessions, t }: { sessions: SessionFact[]; t: Totals }) {
  if (t.byGame.mahjong.sessions === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted">No Mahjong sessions in this range.</p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="text-center">
        <p className="mb-1 text-[10px] uppercase tracking-widest text-muted">Mahjong profit</p>
        <p
          data-testid="mahjong-total"
          className={`text-3xl font-extrabold ${
            t.byGame.mahjong.netCents < 0 ? "text-danger" : "text-brand-strong"
          }`}
        >
          {money(t.byGame.mahjong.netCents)}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Tile label="Sessions played" value={String(t.byGame.mahjong.sessions)} />
        <Tile
          label="Hand win rate"
          value={pct(rate(t.handsWon, t.handsPlayed))}
          sub={`${t.handsWon} of ${t.handsPlayed}`}
          testId="mahjong-hu-rate"
        />
        <Tile
          label="Zimo rate"
          value={pct(rate(t.zimoWins, t.handsWon))}
          sub={`${t.zimoWins} of ${t.handsWon} wins self-drawn`}
          testId="mahjong-zimo-rate"
        />
        <Tile
          label="Shooting rate"
          value={pct(rate(t.shotHands, t.lostHands))}
          sub={`${t.shotHands} of ${t.lostHands} lost hands`}
          tone={rate(t.shotHands, t.lostHands) !== null ? "neg" : undefined}
          testId="mahjong-shooting-rate"
        />
        <Tile
          label="Yao rate"
          value={pct(rate(t.yao + t.anyao, t.handsPlayed))}
          sub={`${t.yao} yao · ${t.anyao} anyao`}
          testId="mahjong-yao-rate"
        />
        <Tile
          label="Gang rate"
          value={pct(rate(t.gang + t.angang, t.handsPlayed))}
          sub={`${t.gang} gang · ${t.angang} angang`}
          testId="mahjong-gang-rate"
        />
        <Tile
          label="Dealer win rate"
          value={pct(rate(t.dealerWins, t.dealerHands))}
          sub={`${t.dealerWins} of ${t.dealerHands} dealer hands`}
        />
        <Tile
          label="Average tai"
          value={t.taiWins ? (t.taiTotal / t.taiWins).toFixed(1) : "—"}
          sub="on your wins"
        />
      </div>

      <SplitDonut
        title="How you win"
        centerLabel="wins"
        testId="chart-mahjong-modes"
        slices={[
          { label: "自摸 Zimo", value: t.zimoWins },
          { label: "Direct", value: t.directWins },
          { label: "包 Bao", value: t.baoWins },
        ]}
      />
      <SplitDonut
        title="Declarations"
        centerLabel="declared"
        testId="chart-mahjong-declarations"
        slices={[
          { label: "咬 Yao", value: t.yao },
          { label: "暗咬 Anyao", value: t.anyao },
          { label: "槓 Gang", value: t.gang },
          { label: "暗槓 Angang", value: t.angang },
        ]}
      />
      <TrendLine points={cumulative(sessions)} />
    </div>
  );
}

/** useSearchParams() can't run during prerender, so the part that reads the
 * ?player= target lives under a Suspense boundary and the route stays
 * static. */
export default function StatsPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
          <p className="text-center text-sm text-muted">Loading…</p>
        </main>
      }
    >
      <StatsView />
    </Suspense>
  );
}

function StatsView() {
  const router = useRouter();
  const search = useSearchParams();
  const { user, checked } = useStoredUser();
  // Viewing a friend's stats is the same page against a different player —
  // the API returns an identical shape, gated on friendship.
  const viewing = search.get("player");
  const [tab, setTab] = useState<Tab>("overview");
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [all, setAll] = useState<SessionFact[] | null>(null);
  const [whose, setWhose] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    request<StatsFactsResponse>(viewing ? `/stats/facts/${viewing}` : "/stats/facts")
      .then((r) => {
        if (cancelled) return;
        setAll(r.sessions);
        setWhose(viewing ? (r.player?.display_name ?? "Your friend") : null);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't load stats.");
      });
    return () => {
      cancelled = true;
    };
  }, [user, viewing]);

  // Everything below is derived, so changing a filter re-renders instantly
  // instead of costing a round trip.
  const scoped = useMemo(() => {
    if (!all) return [];
    const byTab = tab === "overview" ? all : all.filter((s) => s.game_type === tab);
    return applyFilters(byTab, filters);
  }, [all, filters, tab]);
  const t = useMemo(() => totals(scoped), [scoped]);

  if (!user) return null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-5 flex items-center gap-3">
        <button
          onClick={() => router.push(viewing ? "/friends" : "/")}
          data-testid="back-btn"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="truncate text-lg font-extrabold text-brand">
          {whose ? `${whose}'s Stats` : "My Stats"}
        </h1>
      </div>

      {error && (
        <p data-testid="stats-error" className="mb-4 text-center text-sm text-danger">
          {error}
        </p>
      )}

      {!all ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : all.length === 0 ? (
        <p data-testid="stats-empty" className="py-8 text-center text-sm text-muted">
          No finished games yet — play a room to see your stats here.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-2">
            {(["overview", "taidi", "mahjong"] as const).map((x) => (
              <button
                key={x}
                type="button"
                onClick={() => setTab(x)}
                data-testid={`stats-tab-${x}`}
                className={`rounded-xl border px-2 py-2 text-xs font-semibold capitalize ${
                  tab === x
                    ? "border-brand-strong bg-[#FFF8E1] text-brand"
                    : "border-border bg-surface text-muted"
                }`}
              >
                {x}
              </button>
            ))}
          </div>

          <FilterBar
            filters={filters}
            setFilters={setFilters}
            shown={scoped.length}
            total={tab === "overview" ? all.length : all.filter((s) => s.game_type === tab).length}
          />

          {scoped.length === 0 ? (
            <p data-testid="stats-no-match" className="py-8 text-center text-sm text-muted">
              No sessions match these filters.
            </p>
          ) : tab === "overview" ? (
            <OverviewTab
              sessions={scoped}
              t={t}
              filters={filters}
              setFilters={setFilters}
              onSelectRoom={viewing ? undefined : (roomId) => router.push(`/room/${roomId}`)}
            />
          ) : tab === "taidi" ? (
            <TaidiTab sessions={scoped} t={t} />
          ) : (
            <MahjongTab sessions={scoped} t={t} />
          )}
        </div>
      )}
    </main>
  );
}
