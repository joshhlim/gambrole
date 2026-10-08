"use client";

import { useState } from "react";
import { devLogin, passwordAuth, type CurrentUser } from "@/lib/auth";
import SupabaseAuthForm from "./SupabaseAuthForm";

/**
 * Whichever sign-in the app is running with: email + password (Supabase or
 * local mode), or dev mode's name-only form. Shared by home and the pages a
 * shared link lands on signed out (claim a guest, join a group).
 */
export default function SignInPanel({
  onSignedIn,
}: {
  onSignedIn?: (user: CurrentUser, notice?: string) => void;
}) {
  const [nameInput, setNameInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (passwordAuth) {
    return <SupabaseAuthForm onSignedIn={(u, notice) => onSignedIn?.(u, notice)} />;
  }

  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    const name = nameInput.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      // storeAuth inside devLogin announces this; useStoredUser hears it.
      const auth = await devLogin(name);
      onSignedIn?.(auth.user);
    } catch {
      setError("Couldn't sign in. Is the API running?");
      setBusy(false);
    }
  }

  return (
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
        className="w-full rounded-xl bg-primary py-3 text-sm font-semibold text-on-primary disabled:opacity-50"
      >
        Continue
      </button>
      {error && <p className="text-center text-sm text-danger">{error}</p>}
    </form>
  );
}
