import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FileUp, Plus, Search, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input, Select } from "@/components/ui/Input";
import { DaySelector } from "@/components/layout/DaySelector";
import { MonthSelector } from "@/components/layout/MonthSelector";
import { YearSelector } from "@/components/layout/YearSelector";
import {
  TransactionsTable,
  type TransactionSelectMode,
} from "@/components/transactions/TransactionsTable";
import { TransactionFormModal } from "@/components/transactions/TransactionFormModal";
import { useTransactions, useDeleteTransaction, useTransactionYears } from "@/hooks/useTransactions";
import { useAccounts } from "@/hooks/useAccounts";
import { useCategories } from "@/hooks/useCategories";
import { useTags } from "@/hooks/useTags";
import { fetchTransactionById, type TransactionSort } from "@/api/transactions";
import { formatCurrency, formatSignedCurrency } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { buildHierarchicalCategories, translateCategoryName } from "@/lib/categoryLabels";
import type { Transaction, TransactionType } from "@/types";

const PAGE_SIZE = 20;

/** Parses a query-param month, falling back to `fallback` for anything
 * missing or out of range (e.g. a hand-edited URL). Must check `value`
 * for null before `Number()` — `Number(null)` is 0, not NaN, so a missing
 * param would otherwise silently pass the integer check and clamp to 1. */
function parseMonthParam(value: string | null, fallback: number): number {
  if (value === null) return fallback;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 12 ? parsed : fallback;
}

function parseYearParam(value: string | null, fallback: number): number {
  if (value === null) return fallback;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function TransactionsPage() {
  const { t, language } = useTranslation();
  const now = new Date();
  // Deep-linked from the Dashboard's "All transactions" link, which carries
  // the month/year the user was already looking at (?year=&month=) so this
  // page doesn't reset back to the current month.
  const [searchParams] = useSearchParams();
  const [year, setYear] = useState(() => parseYearParam(searchParams.get("year"), now.getFullYear()));
  const [month, setMonth] = useState(() => parseMonthParam(searchParams.get("month"), now.getMonth() + 1));
  const [accountId, setAccountId] = useState(() => searchParams.get("account_id") ?? "");
  const [type, setType] = useState<TransactionType | "">("");
  const [categoryId, setCategoryId] = useState(() => searchParams.get("category_id") ?? "");
  const [tagId, setTagId] = useState<string>("");
  const [sort, setSort] = useState<TransactionSort>("date_desc");
  const [page, setPage] = useState(1);

  // Raw text follows every keystroke; the debounced value is what actually
  // drives the query, so we're not refetching on every character typed.
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timeout = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(timeout);
  }, [searchInput]);
  const isSearching = search.length > 0;

  const [modalOpen, setModalOpen] = useState(false);
  const [editingTransaction, setEditingTransaction] = useState<Transaction | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [selectedDays, setSelectedDays] = useState<number[]>([]);

  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const { data: tags } = useTags();
  const { data: years } = useTransactionYears();
  const { data, isLoading, isError } = useTransactions({
    // A search looks for a purchase from an unknown month, so it must span
    // every period instead of being boxed into the currently selected one.
    year: isSearching ? undefined : year,
    month: isSearching ? undefined : month,
    days: !isSearching && selectedDays.length > 0 ? selectedDays : undefined,
    search: isSearching ? search : undefined,
    account_id: accountId ? Number(accountId) : undefined,
    type: type || undefined,
    category_id: categoryId ? Number(categoryId) : undefined,
    tag_id: tagId ? Number(tagId) : undefined,
    sort,
    page,
    page_size: PAGE_SIZE,
  });
  const deleteTransaction = useDeleteTransaction();
  const items = data?.items ?? [];

  // Drop row selection when the visible list context changes.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [year, month, accountId, type, categoryId, tagId, sort, page, search, selectedDays]);

  // Day chips belong to the selected month — clear when month/year changes.
  useEffect(() => {
    setSelectedDays([]);
  }, [year, month]);

  const selectionTotals = useMemo(() => {
    let spent = 0;
    let income = 0;
    let refunds = 0;
    let cashback = 0;
    for (const tx of items) {
      if (!selectedIds.has(tx.id)) continue;
      const amount = Number(tx.amount);
      if (tx.type === "expense") spent += amount;
      else if (tx.type === "income") income += amount;
      else if (tx.type === "refund") refunds += amount;
      if (tx.cashback_amount != null) {
        const cb = Number(tx.cashback_amount);
        if (cb !== 0) cashback += cb;
      }
    }
    return {
      spent,
      income,
      refunds,
      cashback,
      net: income + refunds - spent,
      count: selectedIds.size,
    };
  }, [items, selectedIds]);

  function handleSelectClick(_transaction: Transaction, index: number, mode: TransactionSelectMode) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (mode === "fromHere") {
        for (const tx of items.slice(index)) next.add(tx.id);
        return next;
      }
      const id = items[index]?.id;
      if (id == null) return prev;
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  // Grouped by kind and hierarchical within each group (a subcategory right
  // under its own parent, indented) — a bare "Sweets" option next to
  // top-level categories reads as if it were one itself.
  const expenseCategoryOptions = buildHierarchicalCategories(
    (categories ?? []).filter((category) => category.kind === "expense"),
    language
  );
  const incomeCategoryOptions = buildHierarchicalCategories(
    (categories ?? []).filter((category) => category.kind === "income"),
    language
  );

  function openCreateModal() {
    setEditingTransaction(null);
    setModalOpen(true);
  }

  function openEditModal(transaction: Transaction) {
    setEditingTransaction(transaction);
    setModalOpen(true);
  }

  /** Opens a transaction by id (refund → original purchase). Prefers the
   * current page list, then falls back to a search fetch. */
  async function openTransactionById(id: number) {
    const fromList = items.find((item) => item.id === id);
    if (fromList) {
      openEditModal(fromList);
      return;
    }
    const found = await fetchTransactionById(id);
    if (found) openEditModal(found);
  }

  function handleDelete(transaction: Transaction) {
    const message =
      transaction.type === "transfer" && !transaction.has_merge_archive
        ? t("transactions.confirmDeleteTransferNoArchive", { description: transaction.description })
        : t("transactions.confirmDelete", { description: transaction.description });
    if (window.confirm(message)) {
      deleteTransaction.mutate(transaction.id);
    }
  }

  /** Leaves search mode and switches the month/year selectors to whichever
   * month the picked transaction is in, so the user lands back in the normal
   * browsing view with it in context instead of a flat result list. */
  function handleJumpToMonth(transaction: Transaction) {
    const date = new Date(`${transaction.date}T00:00:00`);
    setYear(date.getFullYear());
    setMonth(date.getMonth() + 1);
    setSelectedDays([]);
    setSearchInput("");
    setSearch("");
    setPage(1);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex min-w-0 items-center gap-3">
            <div className={`min-w-0 flex-1 ${isSearching ? "pointer-events-none opacity-50" : ""}`}>
              <MonthSelector
                month={month}
                onChange={(value) => {
                  setMonth(value);
                  setSelectedDays([]);
                  setPage(1);
                }}
              />
            </div>
            <div className={isSearching ? "pointer-events-none opacity-50" : ""}>
              <YearSelector
                years={years ?? [now.getFullYear()]}
                year={year}
                onChange={(value) => {
                  setYear(value);
                  setSelectedDays([]);
                  setPage(1);
                }}
              />
            </div>
          </div>
          {!isSearching && (
            <DaySelector
              year={year}
              month={month}
              selectedDays={selectedDays}
              onChange={(days) => {
                setSelectedDays(days);
                setPage(1);
              }}
            />
          )}
        </div>
        <div className="flex gap-2">
          <Link to="/transactions/import" className="flex-1 sm:flex-none">
            <Button variant="secondary" className="w-full sm:w-auto">
              <FileUp size={16} />
              {t("transactions.importButton")}
            </Button>
          </Link>
          <Button onClick={openCreateModal} className="flex-1 sm:w-auto">
            <Plus size={16} />
            {t("transactions.addButton")}
          </Button>
        </div>
      </div>

      <div className="relative">
        <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
        <Input
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder={t("transactions.searchPlaceholder")}
          className="pl-9 pr-9"
        />
        {searchInput && (
          <button
            type="button"
            aria-label={t("common.clear")}
            onClick={() => {
              setSearchInput("");
              setSearch("");
              setPage(1);
            }}
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-text-muted hover:bg-surface-2 hover:text-text-primary"
          >
            <X size={15} />
          </button>
        )}
      </div>
      {isSearching && <p className="text-xs text-text-muted">{t("transactions.searchAcrossAllTime")}</p>}

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <Select
          value={accountId}
          onChange={(event) => {
            setAccountId(event.target.value);
            setPage(1);
          }}
          className="sm:w-56"
        >
          <option value="">{t("transactions.allAccounts")}</option>
          {(accounts ?? []).map((account) => (
            <option key={account.id} value={account.id}>
              {account.name} ({account.currency})
            </option>
          ))}
        </Select>
        <Select
          value={type}
          onChange={(event) => {
            setType(event.target.value as TransactionType | "");
            setPage(1);
          }}
          className="sm:w-48"
        >
          <option value="">{t("transactions.allTypes")}</option>
          <option value="expense">{t("transactions.expense")}</option>
          <option value="income">{t("transactions.income")}</option>
          <option value="transfer">{t("transactions.transfer")}</option>
          <option value="refund">{t("transactions.refund")}</option>
        </Select>
        <Select
          value={categoryId}
          onChange={(event) => {
            setCategoryId(event.target.value);
            setPage(1);
          }}
          className="sm:w-56"
        >
          <option value="">{t("transactions.allCategories")}</option>
          {expenseCategoryOptions.length > 0 && (
            <optgroup label={t("reports.expenseGroup")}>
              {expenseCategoryOptions.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.indented ? `    ↳ ` : ""}
                  {translateCategoryName(category.name)}
                </option>
              ))}
            </optgroup>
          )}
          {incomeCategoryOptions.length > 0 && (
            <optgroup label={t("reports.incomeGroup")}>
              {incomeCategoryOptions.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.indented ? `    ↳ ` : ""}
                  {translateCategoryName(category.name)}
                </option>
              ))}
            </optgroup>
          )}
        </Select>
        {tags && tags.length > 0 && (
          <Select
            value={tagId}
            onChange={(event) => {
              setTagId(event.target.value);
              setPage(1);
            }}
            className="sm:w-48"
          >
            <option value="">{t("transactions.allTags")}</option>
            {tags.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {tag.name}
              </option>
            ))}
          </Select>
        )}
        <Select
          value={sort}
          onChange={(event) => {
            setSort(event.target.value as TransactionSort);
            setPage(1);
          }}
          className="sm:w-56"
        >
          <option value="date_desc">{t("transactions.sortDateDesc")}</option>
          <option value="amount_desc">{t("transactions.sortAmountDesc")}</option>
          <option value="amount_asc">{t("transactions.sortAmountAsc")}</option>
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("nav.transactions")}</CardTitle>
          {data && <span className="text-xs text-text-muted">{t("common.totalCount", { count: data.total })}</span>}
        </CardHeader>
        <CardContent>
          {isError && <p className="py-6 text-center text-sm text-danger">{t("transactions.failedToLoad")}</p>}
          {isLoading ? (
            <p className="py-12 text-center text-sm text-text-muted">{t("common.loading")}</p>
          ) : (
            <TransactionsTable
              items={items}
              viewAccountId={accountId ? Number(accountId) : null}
              onEdit={openEditModal}
              onDelete={handleDelete}
              onOpenTransaction={(id) => void openTransactionById(id)}
              onJumpToMonth={isSearching ? handleJumpToMonth : undefined}
              selectedIds={selectedIds}
              onSelectClick={handleSelectClick}
            />
          )}

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-center gap-3 text-sm">
              <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                {t("common.back")}
              </Button>
              <span className="text-text-muted">{t("common.pageOf", { page, total: totalPages })}</span>
              <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                {t("common.next")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {selectionTotals.count > 0 && (
        <div className="sticky bottom-3 z-10 rounded-xl border border-border bg-surface-1/95 p-3 shadow-sm backdrop-blur sm:p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
              <span className="font-medium text-text-primary">
                {t("transactions.selection.count", { count: selectionTotals.count })}
              </span>
              <span className="tabular-nums text-text-primary">
                {t("transactions.selection.spent")}: {formatCurrency(selectionTotals.spent)}
              </span>
              <span className="tabular-nums text-success">
                {t("transactions.selection.income")}: {formatCurrency(selectionTotals.income)}
              </span>
              <span className="tabular-nums text-success">
                {t("transactions.selection.refunds")}: {formatCurrency(selectionTotals.refunds)}
              </span>
              <span className="tabular-nums text-success">
                {t("transactions.selection.cashback")}: {formatCurrency(selectionTotals.cashback)}
              </span>
              <span
                className={`font-medium tabular-nums ${
                  selectionTotals.net >= 0 ? "text-success" : "text-danger"
                }`}
              >
                {t("transactions.selection.net")}: {formatSignedCurrency(selectionTotals.net)}
              </span>
            </div>
            <Button variant="secondary" onClick={() => setSelectedIds(new Set())} className="w-full sm:w-auto">
              {t("transactions.selection.clear")}
            </Button>
          </div>
        </div>
      )}

      <TransactionFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        transaction={editingTransaction}
        defaultAccountId={accountId ? Number(accountId) : null}
        onOpenTransaction={(id) => void openTransactionById(id)}
      />
    </div>
  );
}
