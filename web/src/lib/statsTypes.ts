// Mirrors api/app/stats_service.py's StatsResponse.model_dump(mode="json")
// (and TaidiPlayerStats/MahjongPlayerStats from core/*/models.py) exactly.
// Keep in sync by hand — see types.ts's identical convention.

import type { GameType } from "./types";

export interface PlayerStats {
  player_id: string;
  display_name: string;
  games: number;
  total_cents: number;
  wins: number;
  losses: number;
  ties: number;
  last_played: string | null;
}

export interface TaidiPlayerStats {
  player_id: string;
  display_name: string;
  lifetime: PlayerStats;
  rounds_played: number;
  round_wins: number;
  round_win_rate: number;
  profit_rounds: number;
  profit_rate: number;
  payer_rounds: number;
  double_rounds: number;
  double_rate: number;
  triple_rounds: number;
  triple_rate: number;
  special_hands_claimed: number;
  best_round_cents: number | null;
  worst_round_cents: number | null;
}

export interface MahjongPlayerStats {
  player_id: string;
  display_name: string;
  lifetime: PlayerStats;
  hands_played: number;
  hu_count: number;
  hu_rate: number;
  win_mode_counts: Record<string, number>;
  win_mode_rates: Record<string, number>;
  avg_tai_on_wins: number;
  tai_distribution: Record<string, number>;
  dealer_hands: number;
  dealer_wins: number;
  dealer_win_rate: number;
  profit_by_kind: Record<string, number>;
  best_hand_chips: number | null;
  worst_hand_chips: number | null;
}

export interface SessionResult {
  room_id: string;
  game_type: GameType;
  ended_at: string;
  net_cents: number;
  cumulative_cents: number;
}

export interface OverviewStats {
  total_cents: number;
  taidi_cents: number;
  mahjong_cents: number;
  mahjong_chips: number;
  total_sessions: number;
  taidi_sessions: number;
  mahjong_sessions: number;
  current_streak: number;
  favorite_game: "taidi" | "mahjong" | "tied" | null;
  last_played: string | null;
  trend: SessionResult[];
}

export interface StatsResponse {
  overview: OverviewStats;
  taidi: TaidiPlayerStats | null;
  mahjong: MahjongPlayerStats | null;
}
