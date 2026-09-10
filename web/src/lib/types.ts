// Mirrors taidi_core's RoomState.model_dump(mode="json") exactly — see
// core/taidi_core/models.py. Keep in sync by hand for now; a generated
// OpenAPI client can replace this once the API is stable.

export type RoomStatus = "lobby" | "in_progress" | "ended" | "disbanded";
export type GameType = "taidi" | "mahjong";
export type RoundPhase = "playing" | "collecting" | "resolved";
export type TransferKind = "cards" | "difference" | "base" | "special";

export interface GameRules {
  card_value_cents: number;
  base_cards: number;
  multipliers_enabled: boolean;
  double_threshold: number;
  triple_threshold: number;
  difference_payouts: boolean;
  special_hands_enabled: boolean;
  special_hand_cards: number;
}

export interface Transfer {
  from_player: string;
  to_player: string;
  cards: number;
  mult: number;
  amount_cents: number;
  kind: TransferKind;
  round_no: number;
}

export interface RoundState {
  round_no: number;
  phase: RoundPhase;
  winner: string | null;
  cards_submitted: Record<string, number>;
  special_counts: Record<string, number>;
  rules_snapshot: GameRules | null;
  engine_version: string | null;
  transfers: Transfer[];
}

export interface Member {
  player_id: string;
  display_name: string;
  is_guest: boolean;
  seat: number;
}

/** GET /rooms/active — the room you're currently in, so a device that has
 * never seen its URL can still get back to a live game. room_id is null
 * when you're not in one. */
export interface ActiveRoom {
  room_id: string | null;
  invite_code?: string;
  game_type?: GameType;
  status?: RoomStatus;
}

export interface RoomState {
  room_id: string;
  game_type: GameType;
  status: RoomStatus;
  seq: number;
  host_id: string;
  members: Record<string, Member>;
  rules: GameRules | null;
  rounds: RoundState[];
  balances: Record<string, number>;
  created_at: string;
  ended_at: string | null;
  invite_code: string;
}
