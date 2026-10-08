/** Marks a player with no account — seated and played by the host. */
export default function GuestTag() {
  return (
    <span
      data-testid="guest-tag"
      className="shrink-0 rounded-full border border-border px-1.5 py-px text-[10px] font-semibold uppercase tracking-wider text-muted"
    >
      Guest
    </span>
  );
}
