import { describe, expect, it } from "vitest";
import { computeCashbackAmount } from "@/lib/cashback";

describe("computeCashbackAmount", () => {
  it("percent_floor: 950 @ 5% → 47 (T-Bank style)", () => {
    expect(computeCashbackAmount(950, 5, "percent_floor")).toBe(47);
  });

  it("base_100: 950 @ 6% → 54", () => {
    expect(computeCashbackAmount(950, 6, "base_100")).toBe(54);
  });

  it("returns 0 for non-positive inputs", () => {
    expect(computeCashbackAmount(0, 5, "percent_floor")).toBe(0);
    expect(computeCashbackAmount(950, 0, "base_100")).toBe(0);
  });
});
