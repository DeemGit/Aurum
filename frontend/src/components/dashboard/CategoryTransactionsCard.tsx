import { useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { TransactionFormModal } from "@/components/transactions/TransactionFormModal";
import { getCategoryIcon } from "@/lib/icons";
import { formatCurrency, formatTransactionDate } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { categoryPath, translateCategoryName } from "@/lib/categoryLabels";
import { useTransactions } from "@/hooks/useTransactions";
import { useCategories } from "@/hooks/useCategories";
import { useAppSettings } from "@/hooks/useSettings";
import type { Transaction } from "@/types";

interface CategoryTransactionsCardProps {
  year: number;
  month: number;
  categoryId: number;
  categoryName: string;
  onClear: () => void;
}

export function CategoryTransactionsCard({
  year,
  month,
  categoryId,
  categoryName,
  onClear,
}: CategoryTransactionsCardProps) {
  const { t } = useTranslation();
  const { data: settings } = useAppSettings();
  const excludeTagIds = (settings?.dashboard_excluded_tags ?? []).map((tag) => tag.id);
  const { data, isLoading } = useTransactions({
    year,
    month,
    category_id: categoryId,
    include_children: true,
    type: "expense",
    page: 1,
    page_size: 50,
    exclude_tag_ids: excludeTagIds.length ? excludeTagIds : undefined,
  });
  const { data: categories } = useCategories();
  const [editingTransaction, setEditingTransaction] = useState<Transaction | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>
            {t("dashboard.categoryTransactionsTitle", {
              name: translateCategoryName(categoryName),
            })}
          </CardTitle>
          <div className="flex shrink-0 items-center gap-3">
            <Button type="button" variant="ghost" className="h-auto px-2 py-1 text-xs" onClick={onClear}>
              {t("dashboard.categoryTransactionsClear")}
            </Button>
            <Link
              to={`/transactions?year=${year}&month=${month}&category_id=${categoryId}`}
              className="text-xs font-medium text-series-1 hover:underline"
            >
              {t("dashboard.allTransactionsLink")}
            </Link>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="py-10 text-center text-sm text-text-muted">{t("common.loading")}</p>
          ) : !data?.items.length ? (
            <p className="py-10 text-center text-sm text-text-muted">
              {t("dashboard.categoryTransactionsEmpty")}
            </p>
          ) : (
            <ul className="divide-y divide-gridline">
              {data.items.map((tx) => {
                const isSplit = tx.splits.length > 0;
                const Icon = getCategoryIcon(tx.category?.icon);
                const color = tx.category?.color ?? "var(--text-muted)";
                const categoryLabel = isSplit
                  ? tx.splits
                      .map((split) =>
                        split.category ? translateCategoryName(split.category.name) : "?",
                      )
                      .join(" + ")
                  : tx.category
                    ? categoryPath(tx.category, categories)
                    : null;
                return (
                  <li key={tx.id}>
                    <button
                      type="button"
                      className="flex w-full items-center gap-3 py-2.5 text-left first:pt-0 last:pb-0 hover:bg-surface-2/60"
                      onClick={() => {
                        setEditingTransaction(tx);
                        setModalOpen(true);
                      }}
                    >
                      <span
                        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                        style={{ backgroundColor: `${color}26` }}
                      >
                        <Icon size={15} style={{ color }} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-text-primary">{tx.description}</span>
                        <span className="block truncate text-xs text-text-muted">
                          {formatTransactionDate(tx.date)} · {tx.account.name}
                          {categoryLabel ? ` · ${categoryLabel}` : ""}
                        </span>
                      </span>
                      <span className="shrink-0 text-sm font-medium tabular-nums text-text-primary">
                        -{formatCurrency(Number(tx.amount))}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <TransactionFormModal
        open={modalOpen}
        onClose={() => {
          setModalOpen(false);
          setEditingTransaction(null);
        }}
        transaction={editingTransaction}
      />
    </>
  );
}
