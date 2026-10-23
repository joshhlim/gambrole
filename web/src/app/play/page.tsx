"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useStoredUser } from "@/lib/auth";

/** Create-or-join, split off the home screen so home only has to offer the
 * two things you actually came for. */
export default function PlayPage() {
  const router = useRouter();
  const { user, checked } = useStoredUser();

  useEffect(() => {
    if (checked && !user) router.replace("/");
  }, [checked, user, router]);

  if (!user) return null;

  return (
    <main className="mx-auto w-full max-w-md flex-1 px-5 py-8">
      <h1 className="mb-6 font-display text-3xl font-extrabold tracking-tight text-brand">Play</h1>

      <div className="space-y-3">
        <button
          onClick={() => router.push("/new")}
          data-testid="create-room-option"
          className="w-full rounded-xl bg-primary py-4 text-sm font-semibold text-on-primary"
        >
          Create a room
        </button>
        <button
          onClick={() => router.push("/play/join")}
          data-testid="join-room-option"
          className="w-full rounded-xl border border-border bg-surface py-4 text-sm font-semibold text-brand"
        >
          Join a room
        </button>
      </div>
    </main>
  );
}
