/** Suggest spending / cashback categories from past transactions with the
 * same description — used by the transaction form's magic-wand button. */
import { fetchTransactions } from "@/api/transactions";
import type { Transaction, TransactionType } from "@/types";

const PAGE_SIZE = 50;
const MAX_PAGES = 5;

export interface CategorySuggestion {
  source: Transaction;
  category_id: number | null;
  splits: { category_id: number; amount: string; note: string | null }[];
}

export interface CashbackSuggestion {
  source: Transaction;
  cashback_category_id: number;
}

export interface HistorySuggestions {
  category: CategorySuggestion | null;
  cashback: CashbackSuggestion | null;
}

function normalizeDescription(value: string): string {
  return value.trim().toLowerCase();
}

function isCategorized(txn: Transaction): boolean {
  if (txn.category_id != null) return true;
  return txn.splits.some((split) => split.category_id != null);
}

function matchesDescription(txn: Transaction, needle: string): boolean {
  return normalizeDescription(txn.description) === needle;
}

/** Walk search pages (newest first) until we find what we need or run out. */
async function collectExactMatches(params: {
  description: string;
  type: TransactionType;
  excludeId?: number | null;
  account_id?: number;
  year?: number;
  month?: number;
}): Promise<Transaction[]> {
  const needle = normalizeDescription(params.description);
  if (!needle) return [];

  const matches: Transaction[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const result = await fetchTransactions({
      search: params.description.trim(),
      type: params.type,
      sort: "date_desc",
      page,
      page_size: PAGE_SIZE,
      account_id: params.account_id,
      year: params.year,
      month: params.month,
    });
    for (const item of result.items) {
      if (params.excludeId != null && item.id === params.excludeId) continue;
      if (!matchesDescription(item, needle)) continue;
      matches.push(item);
    }
    if (result.items.length < PAGE_SIZE || matches.length + (page - 1) * PAGE_SIZE >= result.total) {
      break;
    }
  }
  // API is date_desc; stable-sort by id desc within the same date.
  matches.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1;
    return b.id - a.id;
  });
  return matches;
}

function toCategorySuggestion(txn: Transaction): CategorySuggestion {
  const hasSplits = txn.splits.length > 0;
  return {
    source: txn,
    category_id: hasSplits ? null : txn.category_id,
    splits: hasSplits
      ? txn.splits
          .filter((split) => split.category_id != null)
          .map((split) => ({
            category_id: split.category_id!,
            amount: split.amount,
            note: split.note,
          }))
      : [],
  };
}

/** Look up suggestions for the form's current description / type / account / date. */
export async function suggestFromHistory(params: {
  description: string;
  type: TransactionType;
  accountId: number | null;
  date: string;
  excludeId?: number | null;
}): Promise<HistorySuggestions> {
  const year = Number(params.date.slice(0, 4));
  const month = Number(params.date.slice(5, 7));
  const hasValidMonth = Number.isFinite(year) && Number.isFinite(month) && month >= 1 && month <= 12;

  const [categoryMatches, cashbackMatches] = await Promise.all([
    collectExactMatches({
      description: params.description,
      type: params.type,
      excludeId: params.excludeId,
    }),
    params.accountId != null && hasValidMonth
      ? collectExactMatches({
          description: params.description,
          type: params.type,
          excludeId: params.excludeId,
          account_id: params.accountId,
          year,
          month,
        })
      : Promise.resolve([] as Transaction[]),
  ]);

  const categorized = categoryMatches.find(isCategorized) ?? null;
  const withCashback =
    cashbackMatches.find((txn) => txn.cashback_category_id != null) ?? null;

  return {
    category: categorized ? toCategorySuggestion(categorized) : null,
    cashback: withCashback
      ? {
          source: withCashback,
          cashback_category_id: withCashback.cashback_category_id!,
        }
      : null,
  };
}

/** Scale historical split amounts onto the form's current total (cents). */
export function proportionalSplitAmounts(
  sourceAmounts: string[],
  targetTotal: string,
): string[] {
  const sourceCents = sourceAmounts.map((value) => {
    const n = Math.round(Number(value) * 100);
    return Number.isFinite(n) ? n : 0;
  });
  const sourceSum = sourceCents.reduce((sum, n) => sum + n, 0);
  const targetCents = Math.round(Number(targetTotal) * 100);
  if (!Number.isFinite(targetCents) || targetCents <= 0 || sourceSum <= 0) {
    // Equal shares when we can't scale.
    const n = sourceAmounts.length || 1;
    const each = targetCents > 0 ? Math.floor(targetCents / n) : 0;
    const rem = targetCents > 0 ? targetCents - each * n : 0;
    return sourceAmounts.map((_, index) => ((each + (index < rem ? 1 : 0)) / 100).toFixed(2));
  }
  const scaled = sourceCents.map((cents) => Math.floor((cents * targetCents) / sourceSum));
  let allocated = scaled.reduce((sum, n) => sum + n, 0);
  let i = 0;
  while (allocated < targetCents && scaled.length > 0) {
    scaled[i % scaled.length] += 1;
    allocated += 1;
    i += 1;
  }
  return scaled.map((cents) => (cents / 100).toFixed(2));
}
