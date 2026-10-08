import { getCurrencySymbol } from "./preferences";

/** The app's one money format: signed, two decimals, grouped thousands —
 * so a balance reads the same at the table, in debts and on the charts.
 * The symbol is the player's choice (Settings); display only, nothing is
 * converted. A page showing amounts calls useCurrencySymbol() so it
 * re-renders when that changes. */
export function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}${getCurrencySymbol()}${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Axis-label money: whole units, thousands as "k". */
export function moneyShort(cents: number): string {
  const abs = Math.abs(cents) / 100;
  const sign = cents < 0 ? "-" : "";
  const symbol = getCurrencySymbol();
  return abs >= 1000 ? `${sign}${symbol}${(abs / 1000).toFixed(1)}k` : `${sign}${symbol}${abs.toFixed(0)}`;
}
