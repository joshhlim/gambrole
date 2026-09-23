"use client";

interface TabBarProps<T extends string> {
  tabs: readonly T[];
  active: T;
  onSelect: (tab: T) => void;
  /** Each button gets `${testIdPrefix}-${tab}`. */
  testIdPrefix: string;
  /** For tabs whose label isn't just the key — counts, or real prose. */
  label?: (tab: T) => React.ReactNode;
  className?: string;
}

/**
 * Secondary navigation inside a page.
 *
 * Underlined rather than boxed, on purpose: a bordered pill on a surface
 * reads as one more card in the stack, so the tab row and the content it
 * switches ran together. The rule underneath draws the actual boundary —
 * everything below it is what the selected tab is showing.
 *
 * It also frees the pill style to mean one thing again. Filter chips,
 * dealer, zimo and the rest are toggles you set; these are places you go.
 */
export default function TabBar<T extends string>({
  tabs,
  active,
  onSelect,
  testIdPrefix,
  label,
  className = "",
}: TabBarProps<T>) {
  return (
    <div role="tablist" className={`flex border-b border-border ${className}`}>
      {tabs.map((tab) => {
        const on = tab === active;
        return (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onSelect(tab)}
            data-testid={`${testIdPrefix}-${tab}`}
            // -mb-px drops the active underline onto the container's rule
            // so they're one line, not two a pixel apart.
            className={`-mb-px flex-1 border-b-2 px-2 pb-2.5 text-xs font-semibold capitalize transition-colors ${
              on
                ? "border-brand-strong text-brand"
                : "border-transparent text-muted"
            }`}
          >
            {label ? label(tab) : tab}
          </button>
        );
      })}
    </div>
  );
}
