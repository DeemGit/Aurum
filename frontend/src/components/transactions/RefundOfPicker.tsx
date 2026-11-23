import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { fetchTransactions } from "@/api/transactions";
import { Input } from "@/components/ui/Input";
import { formatCurrency, formatTransactionDate } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import type { RefundOfSummary, Transaction } from "@/types";

const REFUND_OF_INPUT_ID = "refund_of";

/** Display name for a linked purchase — never a bare numeric id when text exists. */
export function purchaseLabel(purchase: {
  id: number;
  description?: string | null;
  merchant?: string | null;
}): string {
  const description = purchase.description?.trim();
  if (description) return description;
  const merchant = purchase.merchant?.trim();
  if (merchant) return merchant;
  return `#${purchase.id}`;
}

interface RefundOfPickerProps {
  value: string;
  onChange: (nextId: string) => void;
  /** Prefill label when editing a refund that already has nested refund_of. */
  linkedSummary?: RefundOfSummary | null;
  /** Open the linked purchase for edit (parent swaps the modal target). */
  onOpenLinked?: (id: number) => void;
  disabled?: boolean;
}

const SEARCH_DEBOUNCE_MS = 300;

export function RefundOfPicker({
  value,
  onChange,
  linkedSummary = null,
  onOpenLinked,
  disabled = false,
}: RefundOfPickerProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(false);
  const [linked, setLinked] = useState<RefundOfSummary | null>(null);
  const requestIdRef = useRef(0);

  // Keep pin in sync with form value + nested summary from the parent row.
  useEffect(() => {
    if (!value) {
      setLinked(null);
      return;
    }
    const id = Number(value);
    if (linkedSummary && linkedSummary.id === id) {
      setLinked(linkedSummary);
      return;
    }
    if (linked && linked.id === id) return;

    let cancelled = false;
    void (async () => {
      try {
        const page = await fetchTransactions({
          search: String(id),
          type: "expense",
          page_size: 20,
        });
        if (cancelled) return;
        const match = page.items.find((item) => item.id === id);
        if (match) {
          setLinked({
            id: match.id,
            description: match.description,
            merchant: match.merchant,
            date: match.date,
            amount: match.amount,
          });
        } else {
          setLinked({
            id,
            description: `#${id}`,
            merchant: null,
            date: "",
            amount: "0",
          });
        }
      } catch {
        if (!cancelled) {
          setLinked({
            id,
            description: `#${id}`,
            merchant: null,
            date: "",
            amount: "0",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // linked is intentionally omitted — we only re-fetch when value/summary change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, linkedSummary]);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed || value) {
      setResults([]);
      setLoading(false);
      return;
    }
    const timer = window.setTimeout(() => {
      const requestId = ++requestIdRef.current;
      setLoading(true);
      void fetchTransactions({ search: trimmed, type: "expense", page_size: 15 })
        .then((page) => {
          if (requestId !== requestIdRef.current) return;
          setResults(page.items);
        })
        .catch(() => {
          if (requestId !== requestIdRef.current) return;
          setResults([]);
        })
        .finally(() => {
          if (requestId === requestIdRef.current) setLoading(false);
        });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query, value]);

  function selectPurchase(tx: Transaction) {
    onChange(String(tx.id));
    setLinked({
      id: tx.id,
      description: tx.description,
      merchant: tx.merchant,
      date: tx.date,
      amount: tx.amount,
    });
    setQuery("");
    setOpen(false);
    setResults([]);
  }

  function unlink() {
    onChange("");
    setLinked(null);
    setQuery("");
    requestAnimationFrame(() => {
      document.getElementById(REFUND_OF_INPUT_ID)?.focus();
    });
  }

  if (value) {
    const pin = linked ?? {
      id: Number(value),
      description: `#${value}`,
      merchant: null,
      date: "",
      amount: "0",
    };
    const label = purchaseLabel(pin);
    return (
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-2 py-1.5">
        <span className="flex max-w-full items-center gap-1 rounded-full bg-surface-2 py-0.5 pl-2 pr-1 text-xs text-text-secondary">
          <button
            type="button"
            disabled={disabled || !onOpenLinked}
            aria-label={t("transactions.form.openPurchase", { name: label })}
            onClick={() => onOpenLinked?.(pin.id)}
            className="max-w-[16rem] truncate text-left text-series-1 hover:underline disabled:cursor-default disabled:text-text-secondary disabled:no-underline sm:max-w-xs"
          >
            {label}
          </button>
          <button
            type="button"
            disabled={disabled}
            aria-label={t("transactions.form.unlinkPurchase")}
            onClick={unlink}
            className="rounded-full p-0.5 text-text-muted hover:bg-surface-1 hover:text-text-primary disabled:opacity-50"
          >
            <X size={11} />
          </button>
        </span>
      </div>
    );
  }

  return (
    <div className="relative">
      <Input
        id={REFUND_OF_INPUT_ID}
        disabled={disabled}
        value={query}
        placeholder={t("transactions.form.refundOfPlaceholder")}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
      />
      {open && query.trim() && (
        <ul className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-lg border border-border bg-surface-1 shadow-lg">
          {loading && (
            <li className="px-3 py-2 text-sm text-text-muted">{t("common.loading")}</li>
          )}
          {!loading && results.length === 0 && (
            <li className="px-3 py-2 text-sm text-text-muted">
              {t("transactions.form.refundOfNoResults")}
            </li>
          )}
          {!loading &&
            results.map((tx) => (
              <li key={tx.id}>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectPurchase(tx)}
                  className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-surface-2"
                >
                  <span className="truncate text-sm text-text-primary">{purchaseLabel(tx)}</span>
                  <span className="truncate text-xs text-text-muted">
                    {formatTransactionDate(tx.date, true)} ·{" "}
                    {formatCurrency(tx.amount, tx.account.currency)}
                    {tx.account?.name ? ` · ${tx.account.name}` : ""}
                  </span>
                </button>
              </li>
            ))}
        </ul>
      )}
    </div>
  );
}
