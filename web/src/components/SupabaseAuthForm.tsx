"use client";

import { useEffect, useState } from "react";
import { requestPasswordReset, signInWithPassword, signUpWithPassword, type CurrentUser } from "@/lib/auth";
import { friendsApi } from "@/lib/friendsApi";
import { ApiError } from "@/lib/api";

type View = "login" | "signup" | "forgot";

const inputCls =
  "w-full rounded-xl border border-border bg-surface px-4 py-3 text-sm outline-none focus:border-brand-strong";

export default function SupabaseAuthForm({ onSignedIn }: { onSignedIn: (user: CurrentUser) => void }) {
  const [view, setView] = useState<View>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [username, setUsername] = useState("");
  // Checked as you type so a taken handle is refused BEFORE Supabase
  // creates the account — the only point at which a real block is possible.
  // The result is tagged with what was checked, so a stale answer can never
  // be shown against a handle the person has since edited.
  const [handleCheck, setHandleCheck] = useState<{
    for: string;
    available: boolean;
    reason: string | null;
  } | null>(null);
  const wantedHandle = username.trim().replace(/^@/, "").toLowerCase();
  const handleResult = handleCheck?.for === wantedHandle ? handleCheck : null;

  useEffect(() => {
    if (!wantedHandle) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      friendsApi
        .usernameAvailable(wantedHandle)
        .then((r) => {
          if (!cancelled) {
            setHandleCheck({ for: wantedHandle, available: r.available, reason: r.reason });
          }
        })
        .catch(() => {
          // Don't strand someone behind a failing check — the claim itself
          // still validates, so let them through to try.
          if (!cancelled) setHandleCheck({ for: wantedHandle, available: true, reason: null });
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wantedHandle]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  function switchView(v: View) {
    setError(null);
    setNotice(null);
    setPassword("");
    setConfirmPassword("");
    setView(v);
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const auth = await signInWithPassword(email.trim(), password);
      onSignedIn(auth.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't sign in.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSignup(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (handleResult && !handleResult.available) {
      setError(handleResult.reason ?? "That username is taken.");
      return;
    }
    // Re-check at the moment of submit: the debounced result could be
    // stale, and this is the last point where refusing costs nothing.
    setBusy(true);
    try {
      const check = await friendsApi.usernameAvailable(wantedHandle);
      if (!check.available) {
        setHandleCheck({ for: wantedHandle, available: false, reason: check.reason });
        setError(check.reason ?? "That username is taken.");
        setBusy(false);
        return;
      }
    } catch {
      /* fall through — the claim below validates too */
    }
    try {
      const auth = await signUpWithPassword(email.trim(), password, name.trim());
      if (auth) {
        // The account exists now, so the handle can be claimed. A failure
        // here isn't fatal — everyone is given one automatically — so it
        // reports the reason and lets them in rather than blocking signup
        // on a cosmetic field they can change in Settings.
        // Someone can still take it in the gap between the check and here.
        // Rare, but it must not pass silently: report it and send them to
        // Settings rather than pretending they got what they asked for.
        try {
          await friendsApi.setUsername(wantedHandle);
        } catch (err) {
          setNotice(
            err instanceof ApiError
              ? `${err.message} Pick another in Settings.`
              : "Couldn't set that username — pick one in Settings.",
          );
        }
        onSignedIn(auth.user);
      } else {
        // "Confirm email" is enabled on the project — account exists but
        // needs the confirmation link clicked before it can sign in.
        // switchView clears `notice`, so it must run first or this message
        // never shows (both setNotice calls land in the same React batch,
        // and the later one wins).
        switchView("login");
        setNotice("Account created — check your email to confirm it, then log in.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create an account.");
    } finally {
      setBusy(false);
    }
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(email.trim());
      setNotice("Check your email for a password reset link.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the reset link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {view === "login" && (
        <form onSubmit={handleLogin} className="space-y-3">
          <input
            type="email"
            data-testid="email-input"
            placeholder="you@example.com"
            className={inputCls}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
          <input
            type="password"
            data-testid="password-input"
            placeholder="Password"
            className={inputCls}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button
            type="submit"
            disabled={busy || !email.trim() || !password}
            data-testid="continue-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Log In
          </button>
          <div className="flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={() => switchView("forgot")}
              data-testid="forgot-password-link"
              className="text-muted"
            >
              Forgot password?
            </button>
            <button
              type="button"
              onClick={() => switchView("signup")}
              data-testid="show-signup-link"
              className="font-semibold text-brand"
            >
              Create an account
            </button>
          </div>
        </form>
      )}

      {view === "signup" && (
        <form onSubmit={handleSignup} className="space-y-3">
          <input
            data-testid="display-name-input"
            placeholder="Your name"
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <input
            data-testid="signup-username-input"
            placeholder="Username (how friends find you)"
            className={inputCls}
            value={username}
            autoCapitalize="none"
            autoCorrect="off"
            onChange={(e) => setUsername(e.target.value)}
          />
          {handleResult && !handleResult.available && (
            <p data-testid="username-unavailable" className="text-xs text-danger">
              {handleResult.reason}
            </p>
          )}
          {handleResult?.available && (
            <p data-testid="username-available" className="text-xs text-brand-strong">
              @{wantedHandle} is available.
            </p>
          )}
          <input
            type="email"
            data-testid="email-input"
            placeholder="you@example.com"
            className={inputCls}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            type="password"
            data-testid="password-input"
            placeholder="Password"
            className={inputCls}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <input
            type="password"
            data-testid="confirm-password-input"
            placeholder="Confirm password"
            className={inputCls}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
          <button
            type="submit"
            disabled={
              busy ||
              !name.trim() ||
              !email.trim() ||
              !password ||
              !wantedHandle ||
              !handleResult?.available
            }
            data-testid="signup-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Create Account
          </button>
          <button
            type="button"
            onClick={() => switchView("login")}
            data-testid="show-login-link"
            className="w-full text-center text-xs text-muted"
          >
            Already have an account? Log in
          </button>
        </form>
      )}

      {view === "forgot" && (
        <form onSubmit={handleForgot} className="space-y-3">
          <p className="text-center text-xs text-muted">
            Enter your email and we&apos;ll send a link to reset your password.
          </p>
          <input
            type="email"
            data-testid="email-input"
            placeholder="you@example.com"
            className={inputCls}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
          <button
            type="submit"
            disabled={busy || !email.trim()}
            data-testid="send-reset-btn"
            className="w-full rounded-xl bg-brand py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Send Reset Link
          </button>
          <button
            type="button"
            onClick={() => switchView("login")}
            data-testid="show-login-link"
            className="w-full text-center text-xs text-muted"
          >
            Back to log in
          </button>
        </form>
      )}

      {notice && (
        <p data-testid="auth-notice" className="text-center text-sm text-muted">
          {notice}
        </p>
      )}
      {error && (
        <p data-testid="auth-error" className="text-center text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
