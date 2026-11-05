/** Mirrors backend cashback_service.compute_cashback_amount. */

export type CashbackRounding = "percent_floor" | "base_100";

/** Auto cashback is always a whole number; UI may override to cents. */
export function computeCashbackAmount(
  amount: number,
  percent: number,
  rounding: CashbackRounding
): number {
  if (!(amount > 0) || !(percent > 0) || !Number.isFinite(amount) || !Number.isFinite(percent)) {
    return 0;
  }
  let raw: number;
  if (rounding === "base_100") {
    raw = Math.floor(amount / 100) * percent;
  } else {
    raw = (amount * percent) / 100;
  }
  return Math.floor(raw);
}
