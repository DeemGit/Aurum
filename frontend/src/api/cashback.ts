import { api } from "@/api/client";
import type { CashbackCategory } from "@/types";

export interface AccountCashbackRate {
  id: number;
  account_id: number;
  year: number;
  month: number;
  cashback_category_id: number;
  cashback_category: CashbackCategory | null;
  percent: string;
}

export interface CashbackReport {
  account_id: number | null;
  year: number;
  month: number;
  expected_total: string;
  actual_total: string;
  refund_adjustment_total: string;
  lines: {
    cashback_category_id: number | null;
    cashback_category_name: string | null;
    expected_amount: string;
    actual_amount: string;
    refund_adjustment: string;
  }[];
}

export function fetchCashbackCategories(accountId?: number) {
  const params = accountId ? `?account_id=${accountId}` : "";
  return api.get<CashbackCategory[]>(`/cashback-categories${params}`);
}

export function createCashbackCategory(input: {
  account_id: number;
  name: string;
  color?: string | null;
}) {
  return api.post<CashbackCategory>("/cashback-categories", input);
}

export function updateCashbackCategory(
  id: number,
  input: { name?: string; color?: string | null }
) {
  return api.patch<CashbackCategory>(`/cashback-categories/${id}`, input);
}

export function deleteCashbackCategory(id: number) {
  return api.delete<void>(`/cashback-categories/${id}`);
}

export function fetchAccountCashbackRates(accountId: number, year: number, month: number) {
  return api.get<AccountCashbackRate[]>(`/accounts/${accountId}/cashback-rates?year=${year}&month=${month}`);
}

export function upsertAccountCashbackRates(
  accountId: number,
  payload: { year: number; month: number; rates: { cashback_category_id: number; percent: string }[] }
) {
  return api.put<AccountCashbackRate[]>(`/accounts/${accountId}/cashback-rates`, payload);
}

export function copyAccountCashbackRates(
  accountId: number,
  payload: { from_year: number; from_month: number; to_year: number; to_month: number }
) {
  return api.post<AccountCashbackRate[]>(`/accounts/${accountId}/cashback-rates/copy`, payload);
}

export function fetchCashbackReport(year: number, month: number, accountId?: number) {
  const params = new URLSearchParams({ year: String(year), month: String(month) });
  if (accountId) params.set("account_id", String(accountId));
  return api.get<CashbackReport>(`/reports/cashback?${params.toString()}`);
}
