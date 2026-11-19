import { useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ArrowLeftRight, CalendarSearch, Pencil, SquareDivide, StickyNote, Trash2 } from "lucide-react";
import { Dialog } from "@/components/ui/Dialog";
import { getCategoryIcon } from "@/lib/icons";
import { formatCurrency, formatTransactionDate } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { categoryPath, translateCategoryName } from "@/lib/categoryLabels";
import { useCategories } from "@/hooks/useCategories";
import { cn } from "@/lib/utils";
import type { Transaction } from "@/types";

export type TransactionSelectMode = "toggle" | "fromHere";

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
  selectedIds?: Set<number>;
  onSelectClick?: (transaction: Transaction, index: number, mode: TransactionSelectMode) => void;
}

const LONG_PRESS_MS = 480;
const LONG_PRESS_MOVE_PX = 10;

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

interface SelectHitAreaProps {
  children: ReactNode;
  className?: string;
  hasSelection: boolean;
  onSelect: (mode: TransactionSelectMode) => void;
}

/** Icon/description hit target: Ctrl/Meta(+Shift) click, long-press, or short
 * tap while a selection is already active. */
function SelectHitArea({ children, className, hasSelection, onSelect }: SelectHitAreaProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startRef = useRef<{ x: number; y: number } | null>(null);
  const longPressFiredRef = useRef(false);

  function clearTimer() {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    // Mouse with modifiers is handled on click; only arm long-press for touch/pen.
    if (event.pointerType === "mouse") return;
    longPressFiredRef.current = false;
    startRef.current = { x: event.clientX, y: event.clientY };
    clearTimer();
    timerRef.current = setTimeout(() => {
      longPressFiredRef.current = true;
      timerRef.current = null;
      onSelect("toggle");
    }, LONG_PRESS_MS);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!startRef.current || timerRef.current == null) return;
    const dx = event.clientX - startRef.current.x;
    const dy = event.clientY - startRef.current.y;
    if (dx * dx + dy * dy > LONG_PRESS_MOVE_PX * LONG_PRESS_MOVE_PX) {
      clearTimer();
    }
  }

  function handlePointerEnd() {
    clearTimer();
    startRef.current = null;
  }

  function handleClick(event: React.MouseEvent<HTMLDivElement>) {
    // Suppress the click that follows a successful long-press.
    if (longPressFiredRef.current) {
      longPressFiredRef.current = false;
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    const withCtrl = event.ctrlKey || event.metaKey;
    if (withCtrl && event.shiftKey) {
      event.preventDefault();
      onSelect("fromHere");
      return;
    }
    if (withCtrl) {
      event.preventDefault();
      onSelect("toggle");
      return;
    }
    // While selecting, a plain click/tap toggles (mobile-friendly deselect).
    if (hasSelection) {
      event.preventDefault();
      onSelect("toggle");
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      className={cn("select-none touch-manipulation", className)}
      onClick={handleClick}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerEnd}
      onPointerCancel={handlePointerEnd}
      onContextMenu={(event) => event.preventDefault()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          if (hasSelection || event.ctrlKey || event.metaKey) {
            onSelect(event.shiftKey && (event.ctrlKey || event.metaKey) ? "fromHere" : "toggle");
          }
        }
      }}
    >
      {children}
    </div>
  );
}

export function TransactionsTable({
  items,
  onEdit,
  onDelete,
  viewAccountId = null,
  onJumpToMonth,
  selectedIds,
  onSelectClick,
}: TransactionsTableProps) {
  const { t } = useTranslation();
  const { data: categories } = useCategories();
  const [noteTransaction, setNoteTransaction] = useState<Transaction | null>(null);
  const hasSelection = (selectedIds?.size ?? 0) > 0;

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
        {items.map((tx, index) => {
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
          const isSelected = selectedIds?.has(tx.id) ?? false;

          return (
            <li
              key={tx.id}
              className={cn(
                "group flex items-center gap-3 py-3",
                isSelected && "rounded-lg bg-surface-2"
              )}
              aria-selected={isSelected}
            >
              <SelectHitArea
                className="flex min-w-0 flex-1 items-center gap-3"
                hasSelection={hasSelection}
                onSelect={(mode) => onSelectClick?.(tx, index, mode)}
              >
                <span
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                  style={{
                    backgroundColor:
                      typeof color === "string" && color.startsWith("#") ? `${color}26` : "var(--surface-2)",
                  }}
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
              </SelectHitArea>

              <span className="flex shrink-0 items-center gap-1.5">
                <span
                  className={`text-sm font-medium tabular-nums ${
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
                {tx.cashback_amount != null && Number(tx.cashback_amount) !== 0 && (
                  <span
                    className="inline-flex items-center rounded-full bg-success/15 px-2 py-0.5 text-xs font-medium tabular-nums text-success"
                    title={t("transactions.cashback")}
                  >
                    {Number(tx.cashback_amount) > 0 ? "+" : ""}
                    {formatCurrency(tx.cashback_amount, tx.account.currency)}
                  </span>
                )}
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
