// Mirrors api/app/stats_facts_service.py's StatsFactsResponse exactly, plus
// the two SessionFacts models from core/*/models.py. Keep in sync by hand —
// see types.ts's identical convention.

import type { GameType } from "./types";

export interface OpponentRef {
  player_id: string;
  display_name: string;
}

/** Counters, never rates — see the Python docstring for why. Everything the
 * stats page shows is a sum of these across the filtered sessions, divided
 * at the very end. */
export interface TaidiSessionFacts {
  rounds_played: number;
  rounds_won: number;
  profit_rounds: number;
  payer_rounds: number;
  double_rounds: number;
  triple_rounds: number;
  special_hands: number;
  trapping_wins: number;
  best_round_cents: number | null;
  worst_round_cents: number | null;
}

export interface MahjongSessionFacts {
  hands_played: number;
  hands_won: number;
  profit_hands: number;
  dealer_hands: number;
  dealer_wins: number;
  zimo_wins: number;
  direct_wins: number;
  bao_wins: number;
  lost_hands: number;
  shot_hands: number;
  yao_count: number;
  anyao_count: number;
  gang_count: number;
  angang_count: number;
  tai_total: number;
  tai_wins: number;
  best_hand_chips: number | null;
  worst_hand_chips: number | null;
}

export interface SessionFact {
  room_id: string;
  game_type: GameType;
  ended_at: string;
  /** Always real cents, so Mahjong and Taidi can be summed together. */
  net_cents: number;
  opponents: OpponentRef[];
  taidi: TaidiSessionFacts | null;
  mahjong: MahjongSessionFacts | null;
}

export interface StatsFactsResponse {
  /** Whose stats these are — lets the page title itself when you're looking
   * at a friend's, and survives a deep link. */
  player: { user_id: string; display_name: string; username: string | null } | null;
  /** Oldest first. */
  sessions: SessionFact[];
}
