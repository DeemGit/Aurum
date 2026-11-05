import { api } from "@/api/client";
import type { AccountInput, AccountWithBalance } from "@/types";

export function fetchAccounts(includeArchived = false) {
  return api.get<AccountWithBalance[]>(`/accounts?include_archived=${includeArchived}`);
}

export function createAccount(input: AccountInput) {
  return api.post<AccountWithBalance>("/accounts", input);
}

export function updateAccount(
  id: number,
  input: Partial<AccountInput> & { is_archived?: boolean; cashback_rounding?: AccountInput["cashback_rounding"] }
) {
  return api.patch<AccountWithBalance>(`/accounts/${id}`, input);
}

export function deleteAccount(id: number) {
  return api.delete<void>(`/accounts/${id}`);
}
