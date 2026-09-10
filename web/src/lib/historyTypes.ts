// Mirrors api/app/history_service.py's HistoryResponse.model_dump(mode="json")
// exactly. Keep in sync by hand — see types.ts's identical convention.

import type { GameType } from "./types";

export interface HistoryEntry {
  room_id: string;
  game_type: GameType;
  ended_at: string;
  net_cents: number;
  settlements_total: number;
  settlements_pending: number;
  settlements_needs_my_approval: number;
  all_settled: boolean;
  /** Who ended the game, or null when the inactivity backstop did it. */
  ended_by: string | null;
  auto_ended: boolean;
}

export interface HistoryResponse {
  games: HistoryEntry[];
}
