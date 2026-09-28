// Mirrors mahjong_core's RoomState.model_dump(mode="json") exactly — see
// core/mahjong_core/models.py. Keep in sync by hand for now, same as
// types.ts does for Taidi.

import type { Member, RoomStatus } from "./types";

export type TransferKind = "yao" | "gang" | "hu" | "bao" | "zimo_bonus" | "klppdd";

export interface TaiPayout {
  hu: number;
  zimo: number;
}

// Money is chips, not cents — real mahjong stakes tables are non-linear by
// tai (a 5-tai hand pays far more than 5x a 1-tai hand), hence a table
// rather than a rate multiplied by tai. tai_table's keys are the tai level
// as a string (1..max_tai) — JSON object keys are always strings, even
// though the wire value started as a Python dict[int, TaiPayout].
export interface MahjongRules {
  base_chips: number;
  yao_chips: number;
  gang_chips: number;
  // Optional extra bonuses toggled per-HU (see MahjongRoom's HuFlow). Both
  // default to 0 (off).
  zimo_bonus_chips: number;
  klppdd_chips: number;
  max_tai: number;
  tai_table: Record<string, TaiPayout>;
}

export interface MahjongTransfer {
  from_player: string;
  to_player: string;
  amount_cents: number;
  kind: TransferKind;
  hand_no: number;
}

export interface HandState {
  hand_no: number;
  wind: number;
  dealer_seat: number;
  had_gang: boolean;
  closed: boolean;
  winner: string | null;
  transfers: MahjongTransfer[];
}

export interface MahjongRoomState {
  room_id: string;
  game_type: "mahjong";
  status: RoomStatus;
  seq: number;
  host_id: string;
  members: Record<string, Member>;
  rules: MahjongRules | null;
  /** See TaidiRoomState.draft_rules. */
  draft_rules: MahjongRules | null;
  hands: HandState[];
  balances: Record<string, number>;
  created_at: string;
  ended_at: string | null;
  pending_wind_decision: boolean;
  invite_code: string;
}

// Fixed seat nicknames — seats are plain 0-3 ints on the wire; these labels
// are purely a frontend display concern (the backend never sees them).
export const SEAT_LABELS = [
  { han: "東", pinyin: "DONG" },
  { han: "南", pinyin: "NAN" },
  { han: "西", pinyin: "XI" },
  { han: "北", pinyin: "BEI" },
] as const;
