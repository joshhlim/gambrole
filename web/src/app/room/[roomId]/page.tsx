"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import type { AnyRoomState, GameType } from "@/lib/types";
import TaidiRoom from "./TaidiRoom";
import MahjongRoom from "./MahjongRoom";
import { RoomLoading, RoomProblem } from "./RoomShell";

const asGame = (g: string | null): GameType | null =>
  g === "taidi" || g === "mahjong" ? g : null;

/**
 * Which game a room is determines which component (and API client, and
 * types) the rest of the page needs. Every link the app builds carries it
 * as ?g=; a bare shared link costs one lookup first. Either way the game
 * component re-checks the real game_type and hands back here if the hint
 * was wrong, rather than reading fields the other game doesn't have.
 */
export default function RoomPage() {
  const { roomId } = useParams<{ roomId: string }>();
  const router = useRouter();
  const search = useSearchParams();
  const { user, checked } = useStoredUser();
  const hinted = asGame(search.get("g"));
  // The room as first fetched here, whether by the lookup or by the game
  // component that turned out to be the wrong one — handed on as the next
  // component's first paint.
  const [looked, setLooked] = useState<AnyRoomState | null>(null);
  const [lookupError, setLookupError] = useState<ApiError | null>(null);
  const gameType = looked?.game_type ?? hinted;

  useEffect(() => {
    // Wait for the client-only auth check to actually complete — redirecting
    // on the pre-check `user === null` would bounce a genuinely signed-in
    // user before useStoredUser's own effect has resolved.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  // Guessing a game on failure would mount the wrong screen against the
  // wrong shape of state, so a failed lookup retries (backing off) until it
  // gets an answer — or stops at one that won't change.
  useEffect(() => {
    if (!user || gameType) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    const lookup = () => {
      api
        .getState(roomId)
        .then((s) => {
          if (!cancelled) setLooked(s);
        })
        .catch((e) => {
          if (cancelled) return;
          const err = e instanceof ApiError ? e : new ApiError(0, "Can't reach the server.");
          setLookupError(err);
          if (err.status === 404 || err.status === 403) return;
          timer = setTimeout(lookup, Math.min(1500 * 2 ** attempt++, 15_000));
        });
    };
    lookup();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [roomId, user, gameType]);

  // The mounted component found the room is the other game: switch, and fix
  // the URL so a reload or a share doesn't repeat the detour.
  const onWrongGame = useCallback(
    (actual: AnyRoomState) => {
      setLooked(actual);
      router.replace(`/room/${roomId}?g=${actual.game_type}`);
    },
    [roomId, router],
  );

  if (!user) return <RoomLoading />;
  if (!gameType) {
    if (lookupError?.status === 404) return <RoomProblem kind="not-found" />;
    if (lookupError?.status === 403) return <RoomProblem kind="forbidden" />;
    return <RoomLoading offline={!!lookupError} />;
  }

  // Keyed on the game so a switch starts the other component from scratch.
  return gameType === "mahjong" ? (
    <MahjongRoom key="mahjong" roomId={roomId} me={user.user_id} initial={looked} onWrongGame={onWrongGame} />
  ) : (
    <TaidiRoom key="taidi" roomId={roomId} me={user.user_id} initial={looked} onWrongGame={onWrongGame} />
  );
}
