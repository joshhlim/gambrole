"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { signOut, useStoredUser } from "@/lib/auth";
import { loadMe, setMe, useMe } from "@/lib/me";
import { profileHref } from "@/lib/profileApi";
import Avatar from "@/components/Avatar";

function Chevron() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden className="text-muted">
      <path d="m9 6 6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ROWS = [
  { href: "/stats", label: "My Stats", testId: "menu-stats" },
  { href: "/history", label: "My Games", testId: "menu-games" },
  { href: "/friends", label: "Friends", testId: "menu-friends" },
  { href: "/settings", label: "Settings", testId: "menu-settings" },
];

const row =
  "flex min-h-12 w-full items-center justify-between px-4 text-left text-sm font-medium text-foreground active:bg-background";

/** The Me tab: who you are, and everything that's yours — what used to
 * hang off the top bar's account menu. */
export default function MePage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const me = useMe();

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  useEffect(() => {
    if (user) loadMe(user.user_id).catch(() => {});
  }, [user]);

  if (!user) return null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-6">
      <button
        onClick={() => me && router.push(profileHref(me))}
        disabled={!me}
        data-testid="menu-profile"
        className="mb-6 flex w-full items-center gap-4 rounded-2xl border border-border bg-surface p-4 text-left active:bg-background"
      >
        {me ? (
          <Avatar name={me.display_name} url={me.avatar_url} accent={me.accent} size={56} />
        ) : (
          <span aria-hidden className="h-14 w-14 shrink-0 animate-pulse rounded-full bg-border" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-display text-lg font-extrabold text-brand">
            {me?.display_name ?? "…"}
          </span>
          <span className="block truncate text-sm text-muted">
            {me?.username ? `@${me.username} · ` : ""}View profile
          </span>
        </span>
        <Chevron />
      </button>

      <div className="overflow-hidden rounded-2xl border border-border bg-surface divide-y divide-border">
        {ROWS.map((r) => (
          <button key={r.href} onClick={() => router.push(r.href)} data-testid={r.testId} className={row}>
            {r.label}
            <Chevron />
          </button>
        ))}
      </div>

      <button
        onClick={async () => {
          await signOut();
          setMe(null);
          // signOut announces itself (see lib/auth.ts): the bars and home
          // page drop the session on their own.
          router.push("/");
        }}
        data-testid="menu-sign-out"
        className="mt-6 min-h-12 w-full rounded-2xl border border-border bg-surface text-sm font-semibold text-danger active:bg-background"
      >
        Sign out
      </button>
    </main>
  );
}
