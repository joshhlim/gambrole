// Mirrors mahjong_core's RoomState.model_dump(mode="json") exactly — see
// core/mahjong_core/models.py. Keep in sync by hand for now, same as
// types.ts does for Taidi.

import type { Member, RoomStatus } from "./types";

export type TransferKind = "yao" | "gang" | "hu" | "bao" | "zimo_bonus" | "klppdd";

export interface TaiPayout {
  hu: number;
  zimo: number;
}

// Amounts are in units of cents_per_unit: 1 (cents) for every game created
// since Mahjong moved to dollars, 50 for older games scored in $0.50 chips —
// so a rule amount is always shown as `amount * cents_per_unit` cents (see
// ruleCents). Balances and transfers are already cents for every game.
// Real mahjong stakes tables are non-linear by tai (a 5-tai hand pays far
// more than 5x a 1-tai hand), hence a table rather than a rate multiplied
// by tai. tai_table's keys are the tai level as a string (1..max_tai) — JSON
// object keys are always strings, even though the wire value started as a
// Python dict[int, TaiPayout].
export interface MahjongRules {
  cents_per_unit: number;
  yao_amount: number;
  gang_amount: number;
  // Optional extra bonuses toggled per-HU (see MahjongRoom's HuFlow). Both
  // default to 0 (off).
  zimo_bonus_amount: number;
  klppdd_amount: number;
  max_tai: number;
  tai_table: Record<string, TaiPayout>;
}

/** A rule amount in cents, whatever unit the game was set up in. */
export function ruleCents(r: MahjongRules, amount: number): number {
  return amount * r.cents_per_unit;
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
  /** See TaidiRoomState.group_id. */
  group_id: string | null;
}

// Fixed seat nicknames — seats are plain 0-3 ints on the wire; these labels
// are purely a frontend display concern (the backend never sees them).
export const SEAT_LABELS = [
  { han: "東", pinyin: "DONG" },
  { han: "南", pinyin: "NAN" },
  { han: "西", pinyin: "XI" },
  { han: "北", pinyin: "BEI" },
] as const;
