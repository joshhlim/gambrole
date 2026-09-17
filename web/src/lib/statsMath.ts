// Filtering and aggregation for the stats page. Pure functions over the
// session rows the API returns, so every filter change is instant instead of
// a ~0.7s round trip to Singapore.
//
// The division always happens LAST: rates are computed from summed counters
// across the filtered set, never by averaging per-session rates (which would
// weight a 3-round night the same as a 40-round one).

import type { GameType } from "./types";
import type { OpponentRef, SessionFact } from "./statsFactsTypes";

export interface Filters {
  /** Only sessions ending within this many days; null = all time. */
  days: number | null;
  /** Only the most recent N sessions; null = all. */
  lastN: number | null;
  /** Only sessions that included every one of these players. */
  withPlayers: string[];
}

export const NO_FILTERS: Filters = { days: null, lastN: null, withPlayers: [] };

export function filtersActive(f: Filters): boolean {
  return f.days !== null || f.lastN !== null || f.withPlayers.length > 0;
}

/** Applies the filters in the order a person would describe them: narrow by
 * date and opponents first, then take the last N of what's left — so "last
 * 10 games with Bob" means ten games with Bob, not "of your last ten games,
 * the ones with Bob". */
export function applyFilters(sessions: SessionFact[], f: Filters): SessionFact[] {
  let out = sessions;
  if (f.days !== null) {
    const cutoff = Date.now() - f.days * 86_400_000;
    out = out.filter((s) => new Date(s.ended_at).getTime() >= cutoff);
  }
  if (f.withPlayers.length > 0) {
    out = out.filter((s) => {
      const ids = new Set(s.opponents.map((o) => o.player_id));
      return f.withPlayers.every((p) => ids.has(p));
    });
  }
  if (f.lastN !== null) out = out.slice(-f.lastN);
  return out;
}

/** Every opponent ever played with, most-played first — the menu for the
 * player filter, and the "most played with" tile. */
export function opponentTally(
  sessions: SessionFact[],
): { opponent: OpponentRef; sessions: number; netCents: number }[] {
  const byId = new Map<string, { opponent: OpponentRef; sessions: number; netCents: number }>();
  for (const s of sessions) {
    for (const o of s.opponents) {
      const row = byId.get(o.player_id) ?? { opponent: o, sessions: 0, netCents: 0 };
      row.opponent = o; // keep the freshest display name
      row.sessions += 1;
      // Your result in the games they were at — not a head-to-head ledger,
      // which the event log can't attribute at more than two players.
      row.netCents += s.net_cents;
      byId.set(o.player_id, row);
    }
  }
  return [...byId.values()].sort((a, b) => b.sessions - a.sessions);
}

export interface Totals {
  sessions: number;
  netCents: number;
  byGame: Record<GameType, { sessions: number; netCents: number }>;
  // Taidi counters
  roundsPlayed: number;
  roundsWon: number;
  profitRounds: number;
  payerRounds: number;
  doubleRounds: number;
  tripleRounds: number;
  specialHands: number;
  trappingWins: number;
  // Mahjong counters
  handsPlayed: number;
  handsWon: number;
  dealerHands: number;
  dealerWins: number;
  zimoWins: number;
  directWins: number;
  baoWins: number;
  lostHands: number;
  shotHands: number;
  yao: number;
  anyao: number;
  gang: number;
  angang: number;
  taiTotal: number;
  taiWins: number;
}

const ZERO: Totals = {
  sessions: 0,
  netCents: 0,
  byGame: { taidi: { sessions: 0, netCents: 0 }, mahjong: { sessions: 0, netCents: 0 } },
  roundsPlayed: 0,
  roundsWon: 0,
  profitRounds: 0,
  payerRounds: 0,
  doubleRounds: 0,
  tripleRounds: 0,
  specialHands: 0,
  trappingWins: 0,
  handsPlayed: 0,
  handsWon: 0,
  dealerHands: 0,
  dealerWins: 0,
  zimoWins: 0,
  directWins: 0,
  baoWins: 0,
  lostHands: 0,
  shotHands: 0,
  yao: 0,
  anyao: 0,
  gang: 0,
  angang: 0,
  taiTotal: 0,
  taiWins: 0,
};

export function totals(sessions: SessionFact[]): Totals {
  const t: Totals = {
    ...ZERO,
    byGame: { taidi: { sessions: 0, netCents: 0 }, mahjong: { sessions: 0, netCents: 0 } },
  };
  for (const s of sessions) {
    t.sessions += 1;
    t.netCents += s.net_cents;
    t.byGame[s.game_type].sessions += 1;
    t.byGame[s.game_type].netCents += s.net_cents;

    const td = s.taidi;
    if (td) {
      t.roundsPlayed += td.rounds_played;
      t.roundsWon += td.rounds_won;
      t.profitRounds += td.profit_rounds;
      t.payerRounds += td.payer_rounds;
      t.doubleRounds += td.double_rounds;
      t.tripleRounds += td.triple_rounds;
      t.specialHands += td.special_hands;
      t.trappingWins += td.trapping_wins;
    }
    const mj = s.mahjong;
    if (mj) {
      t.handsPlayed += mj.hands_played;
      t.handsWon += mj.hands_won;
      t.dealerHands += mj.dealer_hands;
      t.dealerWins += mj.dealer_wins;
      t.zimoWins += mj.zimo_wins;
      t.directWins += mj.direct_wins;
      t.baoWins += mj.bao_wins;
      t.lostHands += mj.lost_hands;
      t.shotHands += mj.shot_hands;
      t.yao += mj.yao_count;
      t.anyao += mj.anyao_count;
      t.gang += mj.gang_count;
      t.angang += mj.angang_count;
      t.taiTotal += mj.tai_total;
      t.taiWins += mj.tai_wins;
    }
  }
  return t;
}

/** Guarded division — an untouched denominator means "no data", not 0%. */
export function rate(numerator: number, denominator: number): number | null {
  return denominator > 0 ? numerator / denominator : null;
}

/** Running total after each session, for the cumulative trend. */
export function cumulative(sessions: SessionFact[]): { session: SessionFact; total: number }[] {
  let running = 0;
  return sessions.map((session) => {
    running += session.net_cents;
    return { session, total: running };
  });
}

/** Which game type you're actually up on. Only meaningful once you've
 * played both, so it reports null rather than crowning a single-entry
 * winner. */
export function bestWorstGame(t: Totals): { best: GameType; worst: GameType } | null {
  const played = (["taidi", "mahjong"] as const).filter((g) => t.byGame[g].sessions > 0);
  if (played.length < 2) return null;
  const [a, b] = played;
  return t.byGame[a].netCents >= t.byGame[b].netCents
    ? { best: a, worst: b }
    : { best: b, worst: a };
}
