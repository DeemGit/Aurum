import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";
import { TagInput } from "@/components/transactions/TagInput";
import { useAccounts } from "@/hooks/useAccounts";
import { useCategories } from "@/hooks/useCategories";
import {
  useCreateTransaction,
  useMergeTransfer,
  useTransferMatches,
  useUpdateTransaction,
} from "@/hooks/useTransactions";
import { fetchAccountCashbackRates, fetchCashbackCategories } from "@/api/cashback";
import { computeCashbackAmount } from "@/lib/cashback";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { buildHierarchicalCategories, translateCategoryName } from "@/lib/categoryLabels";
import { toOccurredAtIso } from "@/lib/csv";
import { formatCurrency, formatDeltaSeconds, formatOccurredAt, formatTransactionDate } from "@/lib/format";
import type { Tag, Transaction, TransactionInput, TransactionSplitInput, TransactionType } from "@/types";

type MergeCandidate = { transaction: Transaction; delta_seconds: number };

interface TransactionFormModalProps {
  open: boolean;
  onClose: () => void;
  transaction?: Transaction | null;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

const EMPTY_FORM = {
  type: "expense" as TransactionType,
  account_id: "",
  category_id: "",
  transfer_account_id: "",
  refund_of_transaction_id: "",
  amount: "",
  transfer_amount: "",
  exchange_rate: "",
  fee_amount: "0",
  cashback_category_id: "",
  cashback_amount: "",
  description: "",
  merchant: "",
  notes: "",
  date: todayIso(),
  time: "00:00",
};

interface SplitRowState {
  key: string;
  category_id: string;
  amount: string;
  note: string;
}

// crypto.randomUUID() only exists in secure contexts (HTTPS/localhost) — on plain
// HTTP (e.g. accessing the app by LAN IP) it's undefined and throws a TypeError.
// This key is only a local React list key, never sent to the backend, so a
// Math.random()-based fallback is fine when the Web Crypto API isn't available.
function generateRowKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `split-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function emptySplitRow(): SplitRowState {
  return { key: generateRowKey(), category_id: "", amount: "", note: "" };
}

// Cents, not floats — a plain Number sum of "0.10" + "0.20" style amounts can
// drift from the transaction total by fractions of a cent, which would
// falsely trip the "must add up exactly" check the backend also enforces.
function toCents(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

export function TransactionFormModal({ open, onClose, transaction }: TransactionFormModalProps) {
  const { t, language } = useTranslation();
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const createTransaction = useCreateTransaction();
  const updateTransaction = useUpdateTransaction();
  const mergeTransferMutation = useMergeTransfer();
  const transferMatches = useTransferMatches(
    open && transaction && (transaction.type === "expense" || transaction.type === "income")
      ? transaction.id
      : null
  );

  const [form, setForm] = useState(EMPTY_FORM);
  const [tags, setTags] = useState<Tag[]>([]);
  const [splitMode, setSplitMode] = useState(false);
  const [splitRows, setSplitRows] = useState<SplitRowState[]>([emptySplitRow(), emptySplitRow()]);
  const [error, setError] = useState<string | null>(null);
  const [previewCandidate, setPreviewCandidate] = useState<MergeCandidate | null>(null);
  const [cashbackAmountTouched, setCashbackAmountTouched] = useState(false);

  const cashbackCategoriesQuery = useQuery({
    queryKey: ["cashback-categories", form.account_id],
    queryFn: () => fetchCashbackCategories(Number(form.account_id)),
    enabled: open && Boolean(form.account_id) && (form.type === "expense" || form.type === "refund"),
  });
  const cashbackYear = form.date ? Number(form.date.slice(0, 4)) : new Date().getFullYear();
  const cashbackMonth = form.date ? Number(form.date.slice(5, 7)) : new Date().getMonth() + 1;
  const cashbackRatesQuery = useQuery({
    queryKey: ["cashback-rates", form.account_id, cashbackYear, cashbackMonth],
    queryFn: () => fetchAccountCashbackRates(Number(form.account_id), cashbackYear, cashbackMonth),
    enabled: open && Boolean(form.account_id) && (form.type === "expense" || form.type === "refund"),
  });

  const selectedAccount = useMemo(
    () => accounts?.find((account) => String(account.id) === form.account_id) ?? null,
    [accounts, form.account_id]
  );

  useEffect(() => {
    if (!open) {
      setPreviewCandidate(null);
      setCashbackAmountTouched(false);
      return;
    }
    if (transaction) {
      const hasSplits = transaction.splits.length > 0;
      // A split's categories always share one parent (see
      // routes/transactions.py's _build_splits) — derive that shared base
      // from whichever split's category is still live. If every split's
      // category was since deleted, there's nothing to derive from; the
      // base field is left blank and the user has to pick one again.
      const baseCategory = hasSplits ? transaction.splits.find((split) => split.category)?.category : null;
      const occurred = transaction.occurred_at ? new Date(transaction.occurred_at) : null;
      const time = occurred
        ? `${String(occurred.getHours()).padStart(2, "0")}:${String(occurred.getMinutes()).padStart(2, "0")}`
        : "00:00";
      setForm({
        type: transaction.type,
        account_id: String(transaction.account_id),
        category_id: hasSplits
          ? baseCategory
            ? String(baseCategory.parent_id ?? baseCategory.id)
            : ""
          : transaction.category_id
            ? String(transaction.category_id)
            : "",
        transfer_account_id: transaction.transfer_account_id ? String(transaction.transfer_account_id) : "",
        refund_of_transaction_id: transaction.refund_of_transaction_id
          ? String(transaction.refund_of_transaction_id)
          : "",
        amount: transaction.amount,
        transfer_amount: transaction.transfer_amount ?? "",
        exchange_rate: transaction.exchange_rate ?? "",
        fee_amount: transaction.fee_amount ?? "0",
        cashback_category_id: transaction.cashback_category_id ? String(transaction.cashback_category_id) : "",
        cashback_amount: transaction.cashback_amount ?? "",
        description: transaction.description,
        merchant: transaction.merchant ?? "",
        notes: transaction.notes ?? "",
        date: transaction.date,
        time,
      });
      setTags(transaction.tags);
      setSplitMode(hasSplits);
      setSplitRows(
        hasSplits
          ? transaction.splits.map((split) => ({
              key: String(split.id),
              category_id: split.category_id ? String(split.category_id) : "",
              amount: split.amount,
              note: split.note ?? "",
            }))
          : [emptySplitRow(), emptySplitRow()]
      );
      // Keep stored cashback until the user changes the cashback category.
      setCashbackAmountTouched(true);
    } else {
      setForm({ ...EMPTY_FORM, account_id: accounts?.[0] ? String(accounts[0].id) : "" });
      setTags([]);
      setSplitMode(false);
      setSplitRows([emptySplitRow(), emptySplitRow()]);
      setCashbackAmountTouched(false);
    }
    setError(null);
  }, [open, transaction, accounts]);

  useEffect(() => {
    if (!open || !form.cashback_category_id || !cashbackCategoriesQuery.data) return;
    const stillValid = cashbackCategoriesQuery.data.some(
      (category) => String(category.id) === form.cashback_category_id
    );
    if (!stillValid) {
      setCashbackAmountTouched(false);
      setForm((prev) => ({ ...prev, cashback_category_id: "", cashback_amount: "" }));
    }
  }, [open, form.cashback_category_id, cashbackCategoriesQuery.data]);

  useEffect(() => {
    if (!open || cashbackAmountTouched) return;
    if (form.type !== "expense" && form.type !== "refund") return;
    if (!form.cashback_category_id || !form.amount || !selectedAccount) {
      if (!form.cashback_category_id && form.cashback_amount !== "") {
        setForm((prev) => ({ ...prev, cashback_amount: "" }));
      }
      return;
    }
    const rate = cashbackRatesQuery.data?.find(
      (row) => String(row.cashback_category_id) === form.cashback_category_id
    );
    const percent = rate ? Number(rate.percent) : 0;
    const computed = computeCashbackAmount(Number(form.amount), percent, selectedAccount.cashback_rounding);
    const next = String(computed);
    if (form.cashback_amount !== next) {
      setForm((prev) => ({ ...prev, cashback_amount: next }));
    }
  }, [
    open,
    cashbackAmountTouched,
    form.type,
    form.cashback_category_id,
    form.amount,
    form.cashback_amount,
    form.account_id,
    form.date,
    selectedAccount,
    cashbackRatesQuery.data,
  ]);

  const kindCategories = (categories ?? []).filter((category) =>
    form.type === "income" ? category.kind === "income" : category.kind === "expense"
  );
  // Subcategories are listed right under their parent (not scattered by
  // name) so the hierarchy set up on the Categories page reads the same way
  // here.
  const relevantCategories = buildHierarchicalCategories(kindCategories, language);

  const isSaving = createTransaction.isPending || updateTransaction.isPending;

  function updateSplitRow(key: string, patch: Partial<SplitRowState>) {
    setSplitRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  }

  function addSplitRow() {
    setSplitRows((prev) => [...prev, emptySplitRow()]);
  }

  function removeSplitRow(key: string) {
    setSplitRows((prev) => (prev.length <= 2 ? prev : prev.filter((row) => row.key !== key)));
  }

  const isSplitEditingNow = form.type !== "transfer" && splitMode;
  const splitAllocatedCents = splitRows.reduce((sum, row) => sum + toCents(row.amount), 0);
  const splitRemainingCents = toCents(form.amount) - splitAllocatedCents;

  // The category select becomes the split's "base" category while
  // splitting — restricted to top-level categories — and each split row can
  // only pick that base itself or one of its direct children (see
  // routes/transactions.py's _build_splits: a split's categories always
  // share one parent).
  const topLevelCategories = relevantCategories.filter((category) => !category.indented);
  const baseChildCategories = kindCategories.filter((category) => category.parent_id === Number(form.category_id));
  const categorySelectOptions = splitMode ? topLevelCategories : relevantCategories;

  function toggleSplitMode() {
    setSplitMode((prev) => {
      const next = !prev;
      if (next) {
        const current = relevantCategories.find((category) => String(category.id) === form.category_id);
        if (current?.parent_id) {
          setForm((f) => ({ ...f, category_id: String(current.parent_id) }));
        }
        setSplitRows([emptySplitRow(), emptySplitRow()]);
      }
      return next;
    });
  }

  function handleBaseCategoryChange(value: string) {
    setForm((prev) => ({ ...prev, category_id: value }));
    if (splitMode) setSplitRows([emptySplitRow(), emptySplitRow()]);
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (!form.account_id) {
      setError(t("transactions.form.errorSelectAccount"));
      return;
    }
    if (form.type === "transfer" && !form.transfer_account_id) {
      setError(t("transactions.form.errorSelectDestination"));
      return;
    }
    if (form.type === "transfer" && form.transfer_account_id === form.account_id) {
      setError(t("transactions.form.errorSameAccount"));
      return;
    }
    if (form.type === "refund" && !form.refund_of_transaction_id) {
      setError(t("transactions.form.errorRefundOf"));
      return;
    }

    // Undefined -> leave the transaction's existing splits untouched on
    // update, and create a normal single-category transaction. [] -> clears
    // splits that used to be there (the user turned split mode off, or
    // switched the transaction to a transfer, which can't carry splits).
    let splits: TransactionSplitInput[] | undefined;
    if (isSplitEditingNow) {
      if (!form.category_id) {
        setError(t("transactions.form.errorSplitNoBaseCategory"));
        return;
      }
      const filledRows = splitRows.filter((row) => row.category_id || row.amount);
      if (filledRows.length < 2) {
        setError(t("transactions.form.errorSplitMinRows"));
        return;
      }
      if (filledRows.some((row) => !row.category_id || !row.amount || Number(row.amount) <= 0)) {
        setError(t("transactions.form.errorSplitIncomplete"));
        return;
      }
      const allocatedCents = filledRows.reduce((sum, row) => sum + toCents(row.amount), 0);
      if (allocatedCents !== toCents(form.amount)) {
        setError(t("transactions.form.errorSplitMismatch"));
        return;
      }
      splits = filledRows.map((row) => ({
        category_id: Number(row.category_id),
        amount: row.amount,
        note: row.note || null,
      }));
    } else if (transaction && transaction.splits.length > 0) {
      splits = [];
    }

    const occurred_at = toOccurredAtIso(form.date, form.time || "00:00");
    const payload: TransactionInput = {
      type: form.type,
      account_id: Number(form.account_id),
      category_id:
        form.type === "transfer" || form.type === "refund" || (splits && splits.length > 0)
          ? null
          : form.category_id
            ? Number(form.category_id)
            : null,
      transfer_account_id: form.type === "transfer" ? Number(form.transfer_account_id) : null,
      refund_of_transaction_id: form.type === "refund" ? Number(form.refund_of_transaction_id) : null,
      amount: form.amount,
      transfer_amount: form.type === "transfer" && form.transfer_amount ? form.transfer_amount : null,
      exchange_rate: form.type === "transfer" && form.exchange_rate ? form.exchange_rate : null,
      fee_amount: form.type === "transfer" ? form.fee_amount || "0" : "0",
      cashback_category_id:
        form.type === "expense" || form.type === "refund"
          ? form.cashback_category_id
            ? Number(form.cashback_category_id)
            : null
          : null,
      cashback_amount:
        (form.type === "expense" || form.type === "refund") && form.cashback_amount !== ""
          ? form.cashback_amount
          : null,
      description: form.description,
      merchant: form.merchant || null,
      notes: form.notes || null,
      date: form.date,
      occurred_at,
      tag_ids: tags.map((tag) => tag.id),
      splits,
    };

    try {
      if (transaction) {
        await updateTransaction.mutateAsync({ id: transaction.id, input: payload });
      } else {
        await createTransaction.mutateAsync(payload);
      }
      onClose();
    } catch {
      setError(t("transactions.form.saveError"));
    }
  }

  return (
    <>
    <Dialog
      open={open}
      onClose={onClose}
      title={transaction ? t("transactions.form.editTitle") : t("transactions.form.newTitle")}
    >
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <Label htmlFor="type">{t("transactions.form.typeLabel")}</Label>
          <Select
            id="type"
            value={form.type}
            onChange={(event) => {
              const nextType = event.target.value as TransactionType;
              setForm((prev) => ({ ...prev, type: nextType, category_id: "" }));
              if (nextType === "transfer" || nextType === "refund") setSplitMode(false);
            }}
          >
            <option value="expense">{t("transactions.form.typeExpense")}</option>
            <option value="income">{t("transactions.form.typeIncome")}</option>
            <option value="transfer">{t("transactions.form.typeTransfer")}</option>
            <option value="refund">{t("transactions.refund")}</option>
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label htmlFor="amount">{t("transactions.form.amountLabel")}</Label>
            <Input
              id="amount"
              type="number"
              step="0.01"
              min="0.01"
              required
              value={form.amount}
              onChange={(event) => setForm((prev) => ({ ...prev, amount: event.target.value }))}
            />
          </div>
          <div>
            <Label htmlFor="date">{t("transactions.form.dateLabel")}</Label>
            <Input
              id="date"
              type="date"
              required
              value={form.date}
              onChange={(event) => setForm((prev) => ({ ...prev, date: event.target.value }))}
            />
          </div>
        </div>

        <div>
          <Label htmlFor="time">{t("transactions.form.timeLabel")}</Label>
          <Input
            id="time"
            type="time"
            value={form.time}
            onChange={(event) => setForm((prev) => ({ ...prev, time: event.target.value }))}
          />
        </div>

        {form.type === "transfer" && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="transfer_amount">{t("transactions.form.transferAmountLabel")}</Label>
              <Input
                id="transfer_amount"
                type="number"
                step="0.01"
                min="0.01"
                value={form.transfer_amount}
                placeholder={form.amount}
                onChange={(event) => setForm((prev) => ({ ...prev, transfer_amount: event.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="exchange_rate">{t("transactions.form.exchangeRateLabel")}</Label>
              <Input
                id="exchange_rate"
                type="number"
                step="0.00000001"
                min="0"
                value={form.exchange_rate}
                onChange={(event) => setForm((prev) => ({ ...prev, exchange_rate: event.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="fee_amount">{t("transactions.form.feeAmountLabel")}</Label>
              <Input
                id="fee_amount"
                type="number"
                step="0.01"
                min="0"
                value={form.fee_amount}
                onChange={(event) => setForm((prev) => ({ ...prev, fee_amount: event.target.value }))}
              />
            </div>
          </div>
        )}

        {form.type === "refund" && (
          <div>
            <Label htmlFor="refund_of">{t("transactions.form.refundOfLabel")}</Label>
            <Input
              id="refund_of"
              type="number"
              required
              min="1"
              value={form.refund_of_transaction_id}
              onChange={(event) => setForm((prev) => ({ ...prev, refund_of_transaction_id: event.target.value }))}
            />
          </div>
        )}

        {(form.type === "expense" || form.type === "refund") && selectedAccount?.type !== "cash" && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="cashback_category">{t("transactions.form.cashbackCategoryLabel")}</Label>
              <Select
                id="cashback_category"
                value={form.cashback_category_id}
                onChange={(event) => {
                  setCashbackAmountTouched(false);
                  setForm((prev) => ({ ...prev, cashback_category_id: event.target.value }));
                }}
              >
                <option value="">{t("transactions.form.cashbackCategoryNone")}</option>
                {(cashbackCategoriesQuery.data ?? []).map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="cashback_amount">
                {form.type === "refund"
                  ? t("transactions.form.cashbackAmountLabel")
                  : t("transactions.form.cashbackAmountExpenseLabel")}
              </Label>
              <Input
                id="cashback_amount"
                type="number"
                step="0.01"
                value={form.cashback_amount}
                onChange={(event) => {
                  setCashbackAmountTouched(true);
                  setForm((prev) => ({ ...prev, cashback_amount: event.target.value }));
                }}
              />
            </div>
          </div>
        )}

        <div>
          <Label htmlFor="description">{t("transactions.form.descriptionLabel")}</Label>
          <Input
            id="description"
            required
            placeholder={t("transactions.form.descriptionPlaceholder")}
            value={form.description}
            onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
          />
        </div>

        <div>
          <Label htmlFor="account">{t("transactions.form.accountLabel")}</Label>
          <Select
            id="account"
            required
            value={form.account_id}
            onChange={(event) => {
              setCashbackAmountTouched(false);
              setForm((prev) => ({
                ...prev,
                account_id: event.target.value,
                cashback_category_id: "",
                cashback_amount: "",
              }));
            }}
          >
            <option value="" disabled>
              {t("transactions.form.selectAccount")}
            </option>
            {accounts?.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name} ({account.currency})
              </option>
            ))}
          </Select>
        </div>

        {form.type === "transfer" ? (
          <div>
            <Label htmlFor="transfer_account">{t("transactions.form.transferAccountLabel")}</Label>
            <Select
              id="transfer_account"
              required
              value={form.transfer_account_id}
              onChange={(event) => setForm((prev) => ({ ...prev, transfer_account_id: event.target.value }))}
            >
              <option value="" disabled>
                {t("transactions.form.selectAccount")}
              </option>
              {accounts
                ?.filter((account) => String(account.id) !== form.account_id)
                .map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} ({account.currency})
                  </option>
                ))}
            </Select>
          </div>
        ) : form.type === "refund" ? null : (
          <div>
            <div className="flex items-center justify-between">
              <Label htmlFor="category">{t("transactions.form.categoryLabel")}</Label>
              <button
                type="button"
                className="mb-1 text-xs text-series-1 hover:underline"
                onClick={toggleSplitMode}
              >
                {splitMode ? t("transactions.form.splitToggleOff") : t("transactions.form.splitToggle")}
              </button>
            </div>

            <Select
              id="category"
              value={form.category_id}
              onChange={(event) => handleBaseCategoryChange(event.target.value)}
            >
              <option value="">{t("transactions.form.noCategory")}</option>
              {categorySelectOptions.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.indented ? `    ↳ ` : ""}
                  {translateCategoryName(category.name)}
                </option>
              ))}
            </Select>

            {splitMode && (
              <div className="mt-2 space-y-2">
                {!form.category_id ? (
                  <p className="text-xs text-text-muted">{t("transactions.form.splitHint")}</p>
                ) : baseChildCategories.length === 0 ? (
                  <p className="text-xs text-text-muted">{t("transactions.form.splitNoChildren")}</p>
                ) : (
                  <p className="text-xs text-text-muted">{t("transactions.form.splitHint")}</p>
                )}
                {splitRows.map((row) => (
                  <div key={row.key} className="space-y-1.5 rounded-lg border border-border bg-surface-1 p-2">
                    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2">
                      <Select
                        aria-label={t("transactions.form.splitCategoryPlaceholder")}
                        className="sm:flex-1"
                        value={row.category_id}
                        disabled={!form.category_id}
                        onChange={(event) => updateSplitRow(row.key, { category_id: event.target.value })}
                      >
                        <option value="" disabled>
                          {t("transactions.form.splitCategoryPlaceholder")}
                        </option>
                        {form.category_id && (
                          <option value={form.category_id}>{t("transactions.form.splitDirectOption")}</option>
                        )}
                        {baseChildCategories.map((category) => (
                          <option key={category.id} value={category.id}>
                            {translateCategoryName(category.name)}
                          </option>
                        ))}
                      </Select>
                      <div className="flex items-center gap-1.5">
                        <Input
                          type="number"
                          step="0.01"
                          min="0.01"
                          className="w-24"
                          placeholder={t("transactions.form.amountLabel")}
                          value={row.amount}
                          onChange={(event) => updateSplitRow(row.key, { amount: event.target.value })}
                        />
                        <button
                          type="button"
                          aria-label={t("transactions.form.splitRemoveRow")}
                          onClick={() => removeSplitRow(row.key)}
                          disabled={splitRows.length <= 2}
                          className="shrink-0 rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-danger disabled:opacity-30"
                        >
                          <X size={15} />
                        </button>
                      </div>
                    </div>
                    <Input
                      className="text-xs"
                      placeholder={t("transactions.form.splitNotePlaceholder")}
                      value={row.note}
                      onChange={(event) => updateSplitRow(row.key, { note: event.target.value })}
                    />
                  </div>
                ))}

                <div className="flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={addSplitRow}
                    className="flex items-center gap-1 rounded-md py-1 text-xs text-series-1 hover:underline"
                  >
                    <Plus size={14} />
                    {t("transactions.form.splitAddRow")}
                  </button>
                  <p className={`text-xs ${splitRemainingCents === 0 ? "text-success" : "text-text-muted"}`}>
                    {splitRemainingCents > 0
                      ? t("transactions.form.splitRemainingLabel", {
                          amount: formatCurrency(splitRemainingCents / 100),
                        })
                      : splitRemainingCents < 0
                        ? t("transactions.form.splitOverAllocatedLabel", {
                            amount: formatCurrency(Math.abs(splitRemainingCents) / 100),
                          })
                        : t("transactions.form.splitFullyAllocatedLabel")}
                  </p>
                </div>
              </div>
            )}
          </div>
        )}

        <div>
          <Label htmlFor="merchant">{t("transactions.form.merchantLabel")}</Label>
          <Input
            id="merchant"
            value={form.merchant}
            onChange={(event) => setForm((prev) => ({ ...prev, merchant: event.target.value }))}
          />
        </div>

        <div>
          <Label htmlFor="notes">{t("transactions.form.notesLabel")}</Label>
          {/* Matches the server's max_length on notes — without it an overlong
              note only fails on save, as an untranslated 422. */}
          <Input
            id="notes"
            maxLength={2000}
            value={form.notes}
            onChange={(event) => setForm((prev) => ({ ...prev, notes: event.target.value }))}
          />
        </div>

        <div>
          <Label htmlFor="transaction-tags">{t("transactions.form.tagsLabel")}</Label>
          <TagInput value={tags} onChange={setTags} />
        </div>

        {transferMatches.data && transferMatches.data.candidates.length > 0 && (
          <div className="space-y-2 rounded-md border border-border p-3">
            <p className="text-xs font-medium text-text-secondary">{t("transactions.form.mergeHint")}</p>
            {transferMatches.data.candidates.slice(0, 3).map((candidate) => {
              const tx = candidate.transaction;
              return (
                <div key={tx.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="min-w-0 flex-1">
                    <button
                      type="button"
                      className="block max-w-full truncate text-left font-medium text-text-primary underline-offset-2 hover:underline"
                      onClick={() => setPreviewCandidate(candidate)}
                    >
                      {tx.description}
                    </button>
                    <span className="block truncate text-xs text-text-muted">
                      {tx.account.name} · {formatOccurredAt(tx.occurred_at)} ·{" "}
                      {formatCurrency(tx.amount, tx.account.currency)} · {formatDeltaSeconds(candidate.delta_seconds)}
                    </span>
                  </span>
                  <Button type="button" variant="secondary" onClick={() => setPreviewCandidate(candidate)}>
                    {t("transactions.form.mergeButton")}
                  </Button>
                </div>
              );
            })}
          </div>
        )}

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSaving}>
            {isSaving ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>

      <Dialog
        open={previewCandidate !== null}
        onClose={() => setPreviewCandidate(null)}
        title={t("transactions.form.mergePreviewTitle")}
      >
        {previewCandidate && (
          <div className="space-y-3 text-sm">
            <dl className="space-y-2">
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewDescription")}</dt>
                <dd className="text-text-primary">{previewCandidate.transaction.description}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewAccount")}</dt>
                <dd className="text-text-primary">{previewCandidate.transaction.account.name}</dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewType")}</dt>
                <dd className="text-text-primary">
                  {t(`transactions.${previewCandidate.transaction.type}` as TranslationKey)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewAmount")}</dt>
                <dd className="text-text-primary tabular-nums">
                  {formatCurrency(
                    previewCandidate.transaction.amount,
                    previewCandidate.transaction.account.currency,
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewDate")}</dt>
                <dd className="text-text-primary">
                  {formatTransactionDate(previewCandidate.transaction.date, true)}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewTime")}</dt>
                <dd className="text-text-primary">{formatOccurredAt(previewCandidate.transaction.occurred_at)}</dd>
              </div>
              {previewCandidate.transaction.merchant && (
                <div>
                  <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewMerchant")}</dt>
                  <dd className="text-text-primary">{previewCandidate.transaction.merchant}</dd>
                </div>
              )}
              {previewCandidate.transaction.notes && (
                <div>
                  <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewNotes")}</dt>
                  <dd className="whitespace-pre-wrap text-text-primary">{previewCandidate.transaction.notes}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-text-muted">{t("transactions.form.mergePreviewDelta")}</dt>
                <dd className="text-text-primary">{formatDeltaSeconds(previewCandidate.delta_seconds)}</dd>
              </div>
            </dl>

            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={() => setPreviewCandidate(null)}>
                {t("transactions.form.mergeCancelPreview")}
              </Button>
              <Button
                type="button"
                disabled={mergeTransferMutation.isPending || !transaction}
                onClick={async () => {
                  if (!transaction || !previewCandidate) return;
                  const sourceIsExpense = transaction.type === "expense";
                  await mergeTransferMutation.mutateAsync({
                    source_transaction_id: sourceIsExpense
                      ? transaction.id
                      : previewCandidate.transaction.id,
                    destination_transaction_id: sourceIsExpense
                      ? previewCandidate.transaction.id
                      : transaction.id,
                  });
                  setPreviewCandidate(null);
                  onClose();
                }}
              >
                {t("transactions.form.mergeConfirm")}
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
