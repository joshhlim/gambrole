"use client";

import { actingAs, post } from "./api";
import type { MahjongRoomState } from "./mahjongTypes";

type Room = MahjongRoomState;

export const mahjongApi = {
  join: (roomId: string) => post<Room>(`/rooms/${roomId}/mahjong/join`),
  leave: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/leave`, { expected_seq: expectedSeq }),
  disband: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/disband`, { expected_seq: expectedSeq }),
  /** Partial maps are merged over the current seats server-side, so a swap
   * only has to name the two players involved. */
  assignSeats: (roomId: string, expectedSeq: number, seatMap: Record<string, number>) =>
    post<Room>(`/rooms/${roomId}/mahjong/assign-seats`, {
      expected_seq: expectedSeq,
      seat_map: seatMap,
    }),
  /** No rules: the server starts on the room's draft_rules. */
  start: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/start`, { expected_seq: expectedSeq }),
  // Hand actions name the hand they're for (hand_no = the last hand as this
  // device saw it) — see api.ts's round_no for why.
  declareYao: (
    roomId: string,
    expectedSeq: number,
    handNo: number,
    targetSeat: number,
    an: boolean,
    asPlayer?: string,
  ) =>
    post<Room>(`/rooms/${roomId}/mahjong/yao`, {
      expected_seq: expectedSeq,
      hand_no: handNo,
      target_seat: targetSeat,
      an,
      ...actingAs(asPlayer),
    }),
  declareGang: (
    roomId: string,
    expectedSeq: number,
    handNo: number,
    target: number | "angang",
    asPlayer?: string,
  ) =>
    post<Room>(`/rooms/${roomId}/mahjong/gang`, {
      expected_seq: expectedSeq,
      hand_no: handNo,
      target,
      ...actingAs(asPlayer),
    }),
  declareHu: (
    roomId: string,
    expectedSeq: number,
    handNo: number,
    mode: "direct" | "zimo" | "bao",
    targetSeat: number | null,
    tai: number,
    zimoBonus: boolean,
    klppdd: boolean,
    asPlayer?: string,
  ) =>
    post<Room>(`/rooms/${roomId}/mahjong/hu`, {
      expected_seq: expectedSeq,
      hand_no: handNo,
      mode,
      target_seat: targetSeat,
      tai,
      zimo_bonus: zimoBonus,
      klppdd,
      ...actingAs(asPlayer),
    }),
  declareNoWin: (roomId: string, expectedSeq: number, handNo: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/no-win`, { expected_seq: expectedSeq, hand_no: handNo }),
  continueWind: (roomId: string, expectedSeq: number, handNo: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/continue-wind`, {
      expected_seq: expectedSeq,
      hand_no: handNo,
    }),
  endGame: (roomId: string, expectedSeq: number) =>
    post<Room>(`/rooms/${roomId}/mahjong/end`, { expected_seq: expectedSeq }),
};
