"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { claimUrl, guestsApi, type GuestClaimLink } from "@/lib/guestsApi";
import type { Member } from "@/lib/types";
import ShareLink from "@/components/ShareLink";

export { default as GuestTag } from "@/components/GuestTag";

// Mirrors the engine's MAX_GUEST_NAME.
const MAX_NAME = 40;

/** The host seats someone with no account. Resolves true when added, so
 * the field only clears once the name is really at the table. */
export function AddGuestForm({
  busy,
  onAdd,
}: {
  busy: boolean;
  onAdd: (name: string) => Promise<boolean>;
}) {
  const [name, setName] = useState("");
  const trimmed = name.trim();
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (trimmed && (await onAdd(trimmed))) setName("");
      }}
      className="flex gap-2"
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={MAX_NAME}
        placeholder="Guest name"
        data-testid="guest-name-input"
        className="min-w-0 flex-1 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm outline-none focus:border-brand-strong"
      />
      <button
        type="submit"
        disabled={busy || !trimmed}
        data-testid="add-guest-btn"
        className="shrink-0 rounded-xl border border-brand-strong px-4 text-sm font-semibold text-brand disabled:opacity-50"
      >
        Add guest
      </button>
    </form>
  );
}

/**
 * Whose turn the host is entering, when guests share the host's phone.
 * Defaults to the host, so a table without guests — or the host's own
 * turn — costs no extra tap.
 */
export function ActingAs({
  me,
  guests,
  actor,
  onPick,
}: {
  me: string;
  guests: Member[];
  actor: string;
  onPick: (playerId: string) => void;
}) {
  const options = [{ id: me, label: "You" }, ...guests.map((g) => ({ id: g.player_id, label: g.display_name }))];
  return (
    <div role="radiogroup" aria-label="Acting for" className="flex flex-wrap items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-muted">For</span>
      {options.map((o) => {
        const on = o.id === actor;
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onPick(o.id)}
            data-testid="acting-as-option"
            className={`max-w-[9rem] truncate rounded-full border px-3 py-1.5 text-xs font-semibold ${
              on ? "border-brand-strong bg-highlight text-brand" : "border-border bg-surface text-muted"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Game over, host only: each guest's link for claiming this game into an
 * account of their own. */
export function GuestLinks({ roomId }: { roomId: string }) {
  const [links, setLinks] = useState<GuestClaimLink[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    guestsApi
      .claimLinks(roomId)
      .then((r) => !cancelled && setLinks(r.guests))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Couldn't load guest links."));
    return () => {
      cancelled = true;
    };
  }, [roomId]);

  if (error) return <p className="text-center text-xs text-danger">{error}</p>;
  if (!links || links.length === 0) return null;

  return (
    <div data-testid="guest-links">
      <p className="mb-2 text-xs uppercase tracking-widest text-muted">Guest links</p>
      <div className="space-y-2">
        {links.map((g) => (
          <div
            key={g.guest_id}
            data-testid="guest-link-row"
            data-player={g.display_name}
            className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2.5 text-sm"
          >
            <span className="min-w-0 flex-1 truncate font-medium">{g.display_name}</span>
            {g.claimed ? (
              <span data-testid="guest-claimed" className="text-xs font-semibold text-muted">
                Claimed
              </span>
            ) : (
              <ShareLink
                url={claimUrl(g.claim_token)}
                title={`${g.display_name}'s game`}
                label="Share link"
                testId="guest-share-btn"
                className="shrink-0 rounded-lg border border-brand-strong px-3 py-1.5 text-xs font-semibold text-brand"
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
