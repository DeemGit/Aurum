import { useState } from "react";
import { ArrowLeftRight, CalendarSearch, Pencil, SquareDivide, StickyNote, Trash2 } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { getCategoryIcon } from "@/lib/icons";
import { formatCurrency, formatTransactionDate } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { categoryPath, translateCategoryName } from "@/lib/categoryLabels";
import { useCategories } from "@/hooks/useCategories";
import type { Transaction } from "@/types";

interface TransactionsTableProps {
  items: Transaction[];
  onEdit: (transaction: Transaction) => void;
  onDelete: (transaction: Transaction) => void;
  /** When set, transfer amounts show +/- relative to this account. */
  viewAccountId?: number | null;
  /** Present only while showing search results, which span every month —
   * lets a row's date carry the year and offers a way to jump back to
   * browsing that transaction's month instead of just listing it flat. */
  onJumpToMonth?: (transaction: Transaction) => void;
}

function transferDirectionLabel(tx: Transaction): string {
  const source = tx.account.name;
  const dest = tx.transfer_account?.name ?? "?";
  return `${source} → ${dest}`;
}

function transferAmountDisplay(
  tx: Transaction,
  viewAccountId: number | null | undefined,
): { sign: string; text: string; className: string } {
  const sourceAmount = formatCurrency(tx.amount, tx.account.currency);
  const destCurrency = tx.transfer_account?.currency ?? tx.account.currency;
  const destRaw = tx.transfer_amount ?? tx.amount;
  const destAmount = formatCurrency(destRaw, destCurrency);

  if (viewAccountId == null) {
    const sameCurrency = tx.account.currency === destCurrency;
    const sameValue = tx.transfer_amount == null || tx.transfer_amount === tx.amount;
    const text = sameCurrency && sameValue ? sourceAmount : `${sourceAmount} / ${destAmount}`;
    return { sign: "", text, className: "text-text-muted" };
  }

  if (viewAccountId === tx.account_id) {
    return { sign: "-", text: sourceAmount, className: "text-text-primary" };
  }

  if (viewAccountId === tx.transfer_account_id) {
    return { sign: "+", text: destAmount, className: "text-success" };
  }

  // Fallback if filter somehow doesn't match either leg.
  return { sign: "", text: sourceAmount, className: "text-text-muted" };
}

export function TransactionsTable({
  items,
  onEdit,
  onDelete,
  viewAccountId = null,
  onJumpToMonth,
}: TransactionsTableProps) {
  const { t } = useTranslation();
  const { data: categories } = useCategories();
  const [noteTransaction, setNoteTransaction] = useState<Transaction | null>(null);

  if (items.length === 0) {
    return (
      <p className="py-12 text-center text-sm text-text-muted">
        {onJumpToMonth ? t("transactions.searchNoneFound") : t("transactions.noneFound")}
      </p>
    );
  }

  return (
    <>
      <ul className="divide-y divide-gridline">
        {items.map((tx) => {
          const isTransfer = tx.type === "transfer";
          const isExpense = tx.type === "expense";
          const isSplit = tx.splits.length > 0;
          const Icon = isTransfer ? ArrowLeftRight : isSplit ? SquareDivide : getCategoryIcon(tx.category?.icon);
          const color = isTransfer || isSplit ? "var(--text-muted)" : tx.category?.color ?? "var(--text-muted)";
          const categoryLabel = isSplit
            ? tx.splits.map((split) => (split.category ? translateCategoryName(split.category.name) : "?")).join(" + ")
            : tx.category
              ? categoryPath(tx.category, categories)
              : null;
          const transferAmount = isTransfer ? transferAmountDisplay(tx, viewAccountId) : null;
          const accountLabel = isTransfer && tx.transfer_account_id
            ? transferDirectionLabel(tx)
            : tx.account.name;

          return (
            <li key={tx.id} className="group flex items-center gap-3 py-3">
              <span
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                style={{ backgroundColor: typeof color === "string" && color.startsWith("#") ? `${color}26` : "var(--surface-2)" }}
              >
                <Icon size={16} style={{ color }} />
              </span>

              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-text-primary">{tx.description}</span>
                <span className="block truncate text-xs text-text-muted">
                  {formatTransactionDate(tx.date, Boolean(onJumpToMonth))} · {accountLabel}
                  {categoryLabel ? ` · ${categoryLabel}` : ""}
                  {tx.tags.length > 0 ? ` · ${tx.tags.map((tag) => tag.name).join(", ")}` : ""}
                </span>
              </span>

              <span
                className={`shrink-0 text-sm font-medium tabular-nums ${
                  transferAmount
                    ? transferAmount.className
                    : isExpense
                      ? "text-text-primary"
                      : "text-success"
                }`}
              >
                {transferAmount
                  ? `${transferAmount.sign}${transferAmount.text}`
                  : `${isExpense ? "-" : "+"}${formatCurrency(tx.amount, tx.account.currency)}`}
              </span>

              <span className="flex shrink-0 gap-1">
                {onJumpToMonth && (
                  <button
                    type="button"
                    aria-label={t("transactions.jumpToMonth")}
                    onClick={() => onJumpToMonth(tx)}
                    className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-text-primary"
                  >
                    <CalendarSearch size={15} />
                  </button>
                )}
                {tx.notes && (
                  <button
                    type="button"
                    aria-label={t("transactions.viewNote")}
                    onClick={() => setNoteTransaction(tx)}
                    className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-text-primary"
                  >
                    <StickyNote size={15} />
                  </button>
                )}
                <button
                  type="button"
                  aria-label={t("common.edit")}
                  onClick={() => onEdit(tx)}
                  className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-text-primary"
                >
                  <Pencil size={15} />
                </button>
                <button
                  type="button"
                  aria-label={t("common.delete")}
                  onClick={() => onDelete(tx)}
                  className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-danger"
                >
                  <Trash2 size={15} />
                </button>
              </span>
            </li>
          );
        })}
      </ul>

      <Dialog
        open={noteTransaction !== null}
        onClose={() => setNoteTransaction(null)}
        title={t("transactions.noteDialogTitle")}
      >
        <p className="whitespace-pre-wrap text-sm text-text-primary">{noteTransaction?.notes}</p>
      </Dialog>
    </>
  );
}
