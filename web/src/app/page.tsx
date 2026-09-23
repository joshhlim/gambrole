"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  devLogin,
  getStoredAuth,
  supabase,
  type CurrentUser,
} from "@/lib/auth";
import type { ActiveRoom } from "@/lib/types";
import SupabaseAuthForm from "@/components/SupabaseAuthForm";
import TopBar from "@/components/TopBar";
import HomeBackdrop from "@/components/HomeBackdrop";

export default function HomePage() {
  const router = useRouter();
  // See useStoredUser's doc comment in lib/auth.ts — a lazy initializer
  // here would mismatch server vs. first-client-hydration render for any
  // returning user. This needs its own setter (login handlers update it
  // immediately) so it can't just use that shared hook.
  const [user, setUser] = useState<CurrentUser | null>(null);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUser(getStoredAuth()?.user ?? null);
  }, []);
  // The way back into a live game from a device that never saw its URL —
  // e.g. picking up on a laptop after the phone died mid-game. Membership
  // lives on the account, not the device, so the seat is still there.
  const [activeRoom, setActiveRoom] = useState<ActiveRoom | null>(null);
  useEffect(() => {
    // No need to clear on sign-out: the button only renders in the
    // signed-in branch, and signing back in refetches.
    if (!user) return;
    let cancelled = false;
    api
      .activeRoom()
      .then((r) => !cancelled && setActiveRoom(r))
      .catch(() => {
        /* a missing rejoin shortcut shouldn't break the home page */
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const [nameInput, setNameInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    const name = nameInput.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const auth = await devLogin(name);
      setUser(auth.user);
    } catch {
      setError("Couldn't sign in. Is the API running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex flex-1 flex-col px-6 py-6">
      <HomeBackdrop />
      {/* Pinned to the top of the page; the hero and the two actions stay
          centred in what's left. */}
      {user && (
        <div className="mx-auto w-full max-w-sm">
          <TopBar />
        </div>
      )}

      <div className="flex w-full flex-1 items-center justify-center">
        <div className="w-full max-w-sm">
          <div className="text-center mb-10">
            <div className="mx-auto mb-4 flex h-16 w-16 rotate-3 items-center justify-center rounded-2xl bg-brand shadow-lg shadow-brand/25">
              <span className="font-display text-3xl font-extrabold text-gold-bright">G</span>
            </div>
            <h1 className="text-3xl font-extrabold tracking-tight text-brand">
              Gam<span className="text-gold">BRO</span>le
            </h1>
            <p className="mt-1.5 text-[10px] uppercase tracking-[0.25em] text-muted">
              Game night, settled
            </p>
          </div>

          {!user ? (
            supabase ? (
              <SupabaseAuthForm onSignedIn={setUser} />
            ) : (
              <form onSubmit={handleDevLogin} className="space-y-3">
                <input
                  className="w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none focus:border-brand-strong"
                  data-testid="display-name-input"
                  placeholder="Your name"
                  value={nameInput}
                  onChange={(e) => setNameInput(e.target.value)}
                  autoFocus
                />
                <button
                  type="submit"
                  disabled={busy || !nameInput.trim()}
                  data-testid="continue-btn"
                  className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
                >
                  Continue
                </button>
              </form>
            )
          ) : (
            <div className="space-y-4">
              {activeRoom?.room_id && (
                <button
                  onClick={() =>
                    router.push(
                      `/room/${activeRoom.room_id}?g=${activeRoom.game_type}`,
                    )
                  }
                  data-testid="rejoin-room-btn"
                  className="w-full rounded-xl bg-brand-strong py-3 text-sm font-semibold text-white"
                >
                  Rejoin Room · {activeRoom.invite_code}
                </button>
              )}

              <button
                onClick={() => router.push("/play")}
                disabled={busy}
                data-testid="play-btn"
                className="w-full rounded-xl bg-brand py-5 text-base font-semibold text-white disabled:opacity-50"
              >
                Play
              </button>

              <button
                onClick={() => router.push("/friends")}
                data-testid="friends-btn"
                className="w-full rounded-xl border border-border bg-surface py-5 text-base font-semibold text-brand"
              >
                Friends
              </button>
            </div>
          )}

          {error && (
            <p className="mt-4 text-center text-sm text-danger">{error}</p>
          )}
        </div>
      </div>
    </main>
  );
}
