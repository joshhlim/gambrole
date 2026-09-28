/** The app's one money format: signed, two decimals, grouped thousands —
 * so a balance reads the same at the table, in debts and on the charts. */
export function money(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Axis-label money: whole dollars, thousands as "k". */
export function moneyShort(cents: number): string {
  const abs = Math.abs(cents) / 100;
  const sign = cents < 0 ? "-" : "";
  return abs >= 1000 ? `${sign}$${(abs / 1000).toFixed(1)}k` : `${sign}$${abs.toFixed(0)}`;
}

/** Mahjong stacks are chips, not money — no currency sign. */
export function chips(amount: number): string {
  return amount.toLocaleString();
}
