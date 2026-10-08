"use client";

import { useState, type ReactNode } from "react";

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
          className="flex-1 rounded-lg bg-danger-fill py-2.5 text-xs font-semibold text-on-primary disabled:opacity-50"
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
