"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";

/** The code entry, on its own page so it only appears once you've said you
 * want to join something. */
export default function JoinRoomPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  async function handleJoin(e: React.FormEvent) {
    e.preventDefault();
    const entered = code.trim().toUpperCase();
    if (!entered) return;
    setBusy(true);
    setError(null);
    try {
      const { room_id, game_type } = await api.byCode(entered);
      // the room page handles joining; ?g= saves it a lookup round trip
      router.push(`/room/${room_id}?g=${game_type}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't find that room.");
      setBusy(false);
    }
  }

  if (!user) return null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-8 flex items-center gap-3">
        <button
          onClick={() => router.push("/play")}
          data-testid="back-btn"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Join a room</h1>
      </div>

      <form onSubmit={handleJoin} className="space-y-3">
        <input
          className="w-full rounded-xl border border-border bg-surface px-4 py-4 text-center text-lg tracking-[0.3em] uppercase outline-none focus:border-brand-strong"
          data-testid="room-code-input"
          placeholder="ROOM CODE"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          maxLength={6}
          autoFocus
          autoCapitalize="characters"
          autoCorrect="off"
        />
        <button
          type="submit"
          disabled={busy || !code.trim()}
          data-testid="join-room-btn"
          className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
        >
          Join
        </button>
        {error && (
          <p data-testid="join-error" className="text-center text-sm text-danger">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
