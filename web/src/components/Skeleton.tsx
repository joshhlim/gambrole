/** Placeholder rows in the shape of the list that's loading, so the page
 * doesn't jump when it lands. */
export function RowsSkeleton({ rows = 3, height = "h-16" }: { rows?: number; height?: string }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className={`${height} animate-pulse rounded-xl border border-border bg-surface`}
          style={{ opacity: 1 - i * 0.2 }}
        />
      ))}
    </div>
  );
}
