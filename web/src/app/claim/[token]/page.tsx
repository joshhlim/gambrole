"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { useCurrencySymbol } from "@/lib/preferences";
import { money } from "@/lib/format";
import { guestsApi, type ClaimPreview } from "@/lib/guestsApi";
import SignInPanel from "@/components/SignInPanel";

const GAME_LABEL = { taidi: "Taidi", mahjong: "Mahjong" } as const;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Where a guest's claim link lands. The preview needs no account, so
 * someone new sees what they'd be claiming before signing up for it.
 */
export default function ClaimPage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { user, checked } = useStoredUser();
  useCurrencySymbol();
  const [preview, setPreview] = useState<ClaimPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    guestsApi
      .preview(token)
      .then((p) => !cancelled && setPreview(p))
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof ApiError ? e.message : "Couldn't load this link.");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function claim() {
    setBusy(true);
    setError(null);
    try {
      const { room_id, game_type } = await guestsApi.claim(token);
      router.replace(`/room/${room_id}?g=${game_type}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't claim this game.");
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-6 flex items-center gap-3">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          aria-label="Home"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Claim game</h1>
      </div>

      {loadError ? (
        <p data-testid="claim-error" className="py-8 text-center text-sm text-muted">
          {loadError}
        </p>
      ) : !preview || !checked ? (
        <p className="text-center text-sm text-muted">Loading…</p>
      ) : (
        <div className="space-y-6">
          <div data-testid="claim-preview" className="rounded-xl border border-border bg-surface px-4 py-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p data-testid="claim-name" className="truncate text-base font-semibold text-foreground">
                  {preview.display_name}
                </p>
                <p className="text-xs text-muted">
                  {GAME_LABEL[preview.game_type]}
                  {preview.ended_at ? ` · ${formatDate(preview.ended_at)}` : ""}
                </p>
                {preview.host_display_name && (
                  <p className="mt-0.5 truncate text-xs text-muted">Host: {preview.host_display_name}</p>
                )}
              </div>
              <p
                data-testid="claim-net"
                className={`shrink-0 text-lg font-bold tabular ${preview.net_cents < 0 ? "text-danger" : "text-brand-strong"}`}
              >
                {money(preview.net_cents)}
              </p>
            </div>
          </div>

          {preview.claimed ? (
            <p data-testid="claim-status" className="text-center text-sm text-muted">
              Already claimed.
            </p>
          ) : preview.status !== "ended" ? (
            <p data-testid="claim-status" className="text-center text-sm text-muted">
              This game hasn&apos;t finished yet.
            </p>
          ) : !user ? (
            <div className="space-y-3">
              <p className="text-center text-xs uppercase tracking-widest text-muted">Sign in to claim</p>
              <SignInPanel />
            </div>
          ) : (
            <div className="space-y-3">
              <button
                onClick={claim}
                disabled={busy}
                data-testid="claim-btn"
                className="w-full truncate rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
              >
                Claim as {user.display_name}
              </button>
              {error && (
                <p data-testid="claim-error" className="text-center text-sm text-danger">
                  {error}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </main>
  );
}
