"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { updateDisplayName, updateEmail, updatePassword } from "@/lib/account";
import { signOut, supabase, useStoredUser, type CurrentUser } from "@/lib/auth";
import { ApiError } from "@/lib/api";
import { friendsApi } from "@/lib/friendsApi";

const inputCls =
  "w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none focus:border-brand-strong";

export default function SettingsPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [email, setEmail] = useState<string | null>(null);
  const [emailChecked, setEmailChecked] = useState(false);

  useEffect(() => {
    // Used to be Supabase-only, back when this page was purely account
    // management. Your username lives here now, and every account has one,
    // so anyone signed in belongs here.
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (!user || !supabase) return;
    supabase.auth.getUser().then(({ data }) => {
      setEmail(data.user?.email ?? null);
      setEmailChecked(true);
    });
  }, [user]);

  // Only the Supabase-backed sections need the email resolved first.
  if (!user || (supabase && !emailChecked)) {
    return <main className="flex-1 flex items-center justify-center text-muted text-sm">Loading…</main>;
  }

  return (
    <main className="flex-1 px-5 py-8 max-w-md mx-auto w-full">
      <div className="flex items-center gap-3 mb-8">
        <button
          onClick={() => router.push("/")}
          data-testid="back-btn"
          className="h-11 w-11 rounded-full border border-border flex items-center justify-center text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Settings</h1>
      </div>

      <div className="space-y-8">
        {/* Your handle is app-level, so it's here whatever you signed in
            with. Everything below it is Supabase account management and
            only exists for real accounts. */}
        <UsernameForm />
        {supabase && (
          <AccountForms
            user={user}
            initialEmail={email ?? ""}
            onSignOut={() => router.push("/")}
          />
        )}
      </div>
    </main>
  );
}

function UsernameForm() {
  const [usernameInput, setUsernameInput] = useState("");
  const [usernameBusy, setUsernameBusy] = useState(false);
  const [usernameMsg, setUsernameMsg] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    friendsApi
      .me()
      .then((p) => !cancelled && setUsernameInput(p.username ?? ""))
      .catch(() => {
        /* the rest of Settings works without it */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSaveUsername(e: React.FormEvent) {
    e.preventDefault();
    setUsernameBusy(true);
    setUsernameMsg(null);
    try {
      const r = await friendsApi.setUsername(usernameInput);
      setUsernameInput(r.username);
      setUsernameMsg(`Saved as @${r.username}.`);
    } catch (err) {
      setUsernameMsg(err instanceof ApiError ? err.message : "Couldn't save that username.");
    } finally {
      setUsernameBusy(false);
    }
  }

  return (
    <div>
      {/* Everyone is given a handle on sign-up; this is where it changes. */}
      <form onSubmit={handleSaveUsername} className="space-y-2">
        <label className="block text-xs text-muted">Username</label>
        <input
          data-testid="settings-username-input"
          className={inputCls}
          value={usernameInput}
          autoCapitalize="none"
          autoCorrect="off"
          onChange={(e) => setUsernameInput(e.target.value)}
        />
        <button
          type="submit"
          disabled={usernameBusy || !usernameInput.trim()}
          data-testid="settings-save-username-btn"
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Save
        </button>
        <p className="text-xs text-muted">
          {usernameMsg ?? "Friends find you by this. Letters, numbers and underscores."}
        </p>
      </form>
    </div>
  );
}

function AccountForms({
  user,
  initialEmail,
  onSignOut,
}: {
  user: CurrentUser;
  initialEmail: string;
  onSignOut: () => void;
}) {
  const [nameInput, setNameInput] = useState(user.display_name);
  const [nameBusy, setNameBusy] = useState(false);
  const [nameMsg, setNameMsg] = useState<string | null>(null);

  const [emailInput, setEmailInput] = useState(initialEmail);
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailMsg, setEmailMsg] = useState<string | null>(null);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [passwordMsg, setPasswordMsg] = useState<string | null>(null);

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    setNameBusy(true);
    setNameMsg(null);
    try {
      await updateDisplayName(nameInput.trim());
      setNameMsg("Saved.");
    } catch (e) {
      setNameMsg(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setNameBusy(false);
    }
  }

  async function handleSaveEmail(e: React.FormEvent) {
    e.preventDefault();
    setEmailBusy(true);
    setEmailMsg(null);
    try {
      await updateEmail(emailInput.trim());
      setEmailMsg("Check your new email to confirm the change.");
    } catch (e) {
      setEmailMsg(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setEmailBusy(false);
    }
  }

  async function handleSavePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordMsg(null);
    if (newPassword.length < 6) {
      setPasswordMsg("Password must be at least 6 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordMsg("Passwords don't match.");
      return;
    }
    setPasswordBusy(true);
    try {
      await updatePassword(newPassword);
      setPasswordMsg("Password updated.");
      setNewPassword("");
      setConfirmPassword("");
    } catch (e) {
      setPasswordMsg(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setPasswordBusy(false);
    }
  }

  async function handleSignOut() {
    await signOut();
    onSignOut();
  }

  return (
    <div className="space-y-8">
      <form onSubmit={handleSaveName} className="space-y-2">
        <label className="block text-xs text-muted">Display name</label>
        <input
          data-testid="settings-name-input"
          className={inputCls}
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
        />
        <button
          type="submit"
          disabled={nameBusy || !nameInput.trim()}
          data-testid="settings-save-name-btn"
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Save
        </button>
        {nameMsg && <p className="text-xs text-muted">{nameMsg}</p>}
      </form>

      <form onSubmit={handleSaveEmail} className="space-y-2">
        <label className="block text-xs text-muted">Email</label>
        <input
          type="email"
          data-testid="settings-email-input"
          className={inputCls}
          value={emailInput}
          onChange={(e) => setEmailInput(e.target.value)}
        />
        <button
          type="submit"
          disabled={emailBusy || !emailInput.trim()}
          data-testid="settings-save-email-btn"
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Save
        </button>
        {emailMsg && <p className="text-xs text-muted">{emailMsg}</p>}
      </form>

      <form onSubmit={handleSavePassword} className="space-y-2">
        <label className="block text-xs text-muted">New password</label>
        <input
          type="password"
          data-testid="settings-new-password-input"
          placeholder="New password"
          className={inputCls}
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
        <input
          type="password"
          data-testid="settings-confirm-password-input"
          placeholder="Confirm new password"
          className={inputCls}
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
        />
        <button
          type="submit"
          disabled={passwordBusy || !newPassword}
          data-testid="settings-save-password-btn"
          className="rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
        >
          Save
        </button>
        {passwordMsg && <p className="text-xs text-muted">{passwordMsg}</p>}
      </form>

      <button
        onClick={handleSignOut}
        data-testid="settings-sign-out-btn"
        className="w-full rounded-xl border border-border py-3 text-sm font-semibold text-muted"
      >
        Sign out
      </button>
    </div>
  );
}
