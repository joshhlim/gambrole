"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { request } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import type { GameType } from "@/lib/types";
import TaidiRoom from "./TaidiRoom";
import MahjongRoom from "./MahjongRoom";

/**
 * Which game a room is determines which component (and API client, and
 * types) the rest of the page needs — but we don't know that until the
 * first response comes back. This does one small untyped fetch just to
 * learn game_type, then hands off entirely to a game-specific component
 * that does its own typed polling from scratch (see ADR-0006).
 */
export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const { user, checked } = useStoredUser();
  // Whoever sent us here (create / join-by-code) already knew the game type,
  // and it never changes for a room — so when it rides along in ?g= we can
  // render the right component immediately instead of spending a whole
  // round trip just to look it up. Shared links without it still fetch.
  const hinted = search.get("g");
  const [gameType, setGameType] = useState<GameType | null>(
    hinted === "taidi" || hinted === "mahjong" ? hinted : null,
  );

  useEffect(() => {
    // Wait for the client-only auth check to actually complete — redirecting
    // on the pre-check `user === null` would bounce a genuinely signed-in
    // user before useStoredUser's own effect has resolved.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user || gameType) return;
    let cancelled = false;
    request<{ game_type: GameType }>(`/rooms/${roomId}/state`)
      .then((s) => {
        if (!cancelled) setGameType(s.game_type);
      })
      .catch(() => {
        // TaidiRoom/MahjongRoom never get to run their own error handling
        // for this — just fall back to Taidi's, the more common case, and
        // let its own polling surface the real error.
        if (!cancelled) setGameType("taidi");
      });
    return () => {
      cancelled = true;
    };
  }, [roomId, user, gameType]);

  if (!user || !gameType) {
    return <main className="flex-1 flex items-center justify-center text-muted text-sm">Loading…</main>;
  }

  return gameType === "mahjong" ? (
    <MahjongRoom roomId={roomId} me={user.user_id} />
  ) : (
    <TaidiRoom roomId={roomId} me={user.user_id} />
  );
}
