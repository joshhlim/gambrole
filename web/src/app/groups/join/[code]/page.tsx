"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useStoredUser } from "@/lib/auth";
import { groupsApi } from "@/lib/groupsApi";
import SignInPanel from "@/components/SignInPanel";

/**
 * Where a group's invite link lands. Opening the link is the decision to
 * join, so signed in it joins straight away (joining twice is harmless);
 * signed out it asks for an account first, then does the same.
 */
export default function JoinGroupPage() {
  const { code } = useParams<{ code: string }>();
  const router = useRouter();
  const { user, checked } = useStoredUser();
  const [error, setError] = useState<string | null>(null);
  const started = useRef<string | null>(null);

  useEffect(() => {
    if (!user || started.current === user.user_id) return;
    started.current = user.user_id;
    groupsApi
      .join(code)
      .then((g) => router.replace(`/groups/${g.group_id}`))
      .catch((e) => {
        setError(
          e instanceof ApiError && e.status === 404
            ? "This invite link doesn't work any more."
            : e instanceof ApiError
              ? e.message
              : "Couldn't join this group.",
        );
      });
  }, [user, code, router]);

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <div className="mb-6 flex items-center gap-3">
        <button
          onClick={() => router.push(user ? "/groups" : "/")}
          data-testid="back-btn"
          aria-label="Back"
          className="flex h-11 w-11 items-center justify-center rounded-full border border-border text-lg font-bold text-brand"
        >
          ←
        </button>
        <h1 className="text-lg font-extrabold text-brand">Join group</h1>
      </div>

      {!checked ? null : !user ? (
        <div className="space-y-3">
          <p className="text-center text-xs uppercase tracking-widest text-muted">Sign in to join</p>
          <SignInPanel />
        </div>
      ) : error ? (
        <p data-testid="group-join-error" className="py-8 text-center text-sm text-muted">
          {error}
        </p>
      ) : (
        <p className="text-center text-sm text-muted">Joining…</p>
      )}
    </main>
  );
}
