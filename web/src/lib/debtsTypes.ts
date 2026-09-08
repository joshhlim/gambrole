// Mirrors api/app/debts_service.py's DebtsResponse/DebtActionResult
// .model_dump(mode="json") exactly. Keep in sync by hand — see types.ts's
// identical convention.

import type { GameType } from "./types";

export type DebtStatus = "pending" | "marked_paid" | "approved";

export interface DebtView {
  settlement_id: string;
  room_id: string;
  game_type: GameType;
  counterparty_id: string;
  counterparty_display_name: string;
  amount_cents: number;
  status: DebtStatus;
  created_at: string;
  updated_at: string;
}

export interface DebtsResponse {
  owing: DebtView[];
  owed: DebtView[];
}

export interface DebtActionResult {
  settlement_id: string;
  status: DebtStatus;
  updated_at: string;
}
