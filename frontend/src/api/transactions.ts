import { api } from "@/api/client";
import type { Transaction, TransactionInput, TransactionPage } from "@/types";

export type TransactionSort = "date_desc" | "amount_desc" | "amount_asc";

export interface TransactionFilters {
  year?: number;
  month?: number;
  start_date?: string;
  end_date?: string;
  account_id?: number;
  category_id?: number;
  /** When true with category_id, also match direct subcategories (dashboard drill-down). */
  include_children?: boolean;
  tag_id?: number;
  type?: string;
  search?: string;
  sort?: TransactionSort;
  page?: number;
  page_size?: number;
}

export function fetchTransactions(filters: TransactionFilters = {}) {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null) params.set(key, String(value));
  });
  return api.get<TransactionPage>(`/transactions?${params.toString()}`);
}

// Used by CSV import's duplicate check (see pages/CsvImportPage.tsx) — needs
// every transaction in the imported date range for one account, not just a
// page of them, to know what's already there. Capped at 25 pages (5000 rows
// at the API's max page_size) so a huge date range can't turn one import
// into an unbounded fetch loop; beyond that, duplicate detection just
// silently covers less of the range instead of hanging.
const MAX_DUPLICATE_CHECK_PAGES = 25;

export async function fetchAllTransactionsInRange(filters: TransactionFilters): Promise<Transaction[]> {
  const pageSize = 200;
  const items: Transaction[] = [];
  for (let page = 1; page <= MAX_DUPLICATE_CHECK_PAGES; page++) {
    const result = await fetchTransactions({ ...filters, page, page_size: pageSize });
    items.push(...result.items);
    if (items.length >= result.total || result.items.length < pageSize) break;
  }
  return items;
}

/** Full range of years to offer in the year picker, from the earliest
 * transaction through the current year (see backend for the "gap year"
 * rationale). */
export function fetchTransactionYears() {
  return api.get<number[]>("/transactions/years");
}

export function createTransaction(input: TransactionInput) {
  return api.post<Transaction>("/transactions", input);
}

/** CSV import — see pages/CsvImportPage.tsx. Validation still fails the whole
 * request on a bad row; rows whose import_hash already exists are skipped. */
export function bulkCreateTransactions(items: TransactionInput[]) {
  return api.post<{ created: number; skipped_duplicates: number; hashes_backfilled: number }>(
    "/transactions/bulk",
    { items },
  );
}

/** Gazprombank HTML history paste → CSV for the import wizard. */
export function convertGpbHtmlStatement(html: string, today: string) {
  return api.post<{ csv: string; row_count: number }>("/transactions/import/gpb-html", { html, today });
}

/** Alfa-Bank HTML history paste → Alfa CSV for the import wizard. */
export function convertAlfaHtmlStatement(html: string, today: string) {
  return api.post<{ csv: string; row_count: number }>("/transactions/import/alfa-html", { html, today });
}

export function fetchTransferMatches(transactionId: number) {
  return api.get<{ candidates: { transaction: Transaction; delta_seconds: number }[] }>(
    `/transactions/${transactionId}/transfer-matches`
  );
}

export function mergeTransfer(payload: {
  source_transaction_id: number;
  destination_transaction_id: number;
  transfer_amount?: string;
  exchange_rate?: string;
  fee_amount?: string;
}) {
  return api.post<Transaction>("/transactions/merge-transfer", payload);
}

/** Existing txs (esp. transfers) an import row can be force-linked to. */
export function fetchImportLinkCandidates(params: {
  account_id: number;
  amount: string;
  date: string;
  type?: "expense" | "income";
}) {
  const qs = new URLSearchParams({
    account_id: String(params.account_id),
    amount: params.amount,
    date: params.date,
  });
  if (params.type) qs.set("type", params.type);
  return api.get<Transaction[]>(`/transactions/import-link-candidates?${qs.toString()}`);
}

/** Attach a statement fingerprint to an existing transaction (no new row). */
export function attachImportHash(
  transactionId: number,
  payload: { account_id: number; import_hash: string },
) {
  return api.post<Transaction>(`/transactions/${transactionId}/import-hashes`, payload);
}

export function updateTransaction(id: number, input: Partial<TransactionInput>) {
  return api.patch<Transaction>(`/transactions/${id}`, input);
}

export function deleteTransaction(id: number) {
  return api.delete<void>(`/transactions/${id}`);
}
