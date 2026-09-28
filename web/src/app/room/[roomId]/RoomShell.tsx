"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { RoomProblemKind } from "./useRoom";

/** Full-screen stand-in for a room that can't be shown at all. */
export function RoomProblem({ kind }: { kind: Exclude<RoomProblemKind, "offline"> }) {
  const router = useRouter();
  return (
    <main className="flex flex-1 items-center justify-center px-5 py-8">
      <div className="w-full max-w-sm space-y-4 text-center">
        <p data-testid="room-problem" className="text-sm text-muted">
          {kind === "not-found" ? "Room not found." : "You're not in this game."}
        </p>
        <button
          onClick={() => router.push("/")}
          data-testid="room-problem-home-btn"
          className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white"
        >
          Home
        </button>
      </div>
    </main>
  );
}

export function RoomLoading({ offline }: { offline?: boolean }) {
  return (
    <main className="flex flex-1 items-center justify-center text-sm text-muted">
      {offline ? "Reconnecting…" : "Loading…"}
    </main>
  );
}

/**
 * The frame both room screens share: a back arrow that only ever
 * minimises (you stay in the room; home's "Rejoin Room" is the way back),
 * a quiet reconnecting marker, and the banner for refused actions.
 *
 * The back arrow is never disabled — a request stuck in flight must not
 * trap anyone on the page.
 */
export function RoomFrame({
  offline,
  banner,
  blockedBy,
  children,
}: {
  offline: boolean;
  banner: string | null;
  blockedBy: string | null;
  children: ReactNode;
}) {
  const router = useRouter();
  const [going, setGoing] = useState(false);

  // The refusal only names the other room, not its game — ask which one it
  // is, so the link lands on the right screen without a lookup detour.
  async function goToActive() {
    if (!blockedBy || going) return;
    setGoing(true);
    const active = await api.activeRoom().catch(() => null);
    const g = active?.room_id === blockedBy ? active.game_type : undefined;
    router.push(`/room/${blockedBy}${g ? `?g=${g}` : ""}`);
  }

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center justify-between gap-3 mb-6">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          aria-label="Back"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        {offline && (
          <span
            data-testid="reconnecting"
            role="status"
            className="rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-muted"
          >
            Reconnecting…
          </span>
        )}
      </div>

      {banner && (
        <div
          data-testid="room-banner"
          role="status"
          className="mb-4 rounded-lg border border-border bg-surface px-4 py-2 text-sm text-muted"
        >
          {banner}
          {blockedBy && (
            <button
              onClick={goToActive}
              disabled={going}
              data-testid="go-to-active-room-btn"
              className="mt-2 w-full rounded-lg bg-brand-strong py-2 text-xs font-semibold text-white disabled:opacity-50"
            >
              Go to your game
            </button>
          )}
        </div>
      )}

      {children}
    </main>
  );
}

/** One line of the room's rules, for settling "wait, what are we playing
 * for?" without leaving the table. */
export function RulesLine({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p data-testid="rules-summary" className="text-center text-[11px] text-muted">
      {text}
    </p>
  );
}

/**
 * A button that asks before it acts — for anything that settles money or
 * can't be taken back. The confirm step replaces the button in place, so
 * the layout doesn't jump and a second stray tap lands on "Cancel"'s side
 * of the row rather than repeating the action.
 */
export function ConfirmAction({
  label,
  prompt,
  confirmLabel,
  testIds,
  busy,
  onConfirm,
  buttonClassName,
}: {
  label: ReactNode;
  prompt: string;
  confirmLabel: string;
  testIds: { open: string; confirm: string; cancel: string };
  busy: boolean;
  onConfirm: () => void;
  buttonClassName: string;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button
        onClick={() => setAsking(true)}
        disabled={busy}
        data-testid={testIds.open}
        className={buttonClassName}
      >
        {label}
      </button>
    );
  }
  return (
    <div className="space-y-2 rounded-xl border border-border bg-surface px-3 py-2.5">
      <p className="text-center text-xs text-muted">{prompt}</p>
      <div className="flex gap-2">
        <button
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
          disabled={busy}
          data-testid={testIds.confirm}
          className="flex-1 rounded-lg bg-danger py-2.5 text-xs font-semibold text-white disabled:opacity-50"
        >
          {confirmLabel}
        </button>
        <button
          onClick={() => setAsking(false)}
          data-testid={testIds.cancel}
          className="flex-1 rounded-lg border border-border py-2.5 text-xs font-semibold text-muted"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
