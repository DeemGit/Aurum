import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";
import { MonthSelector } from "@/components/layout/MonthSelector";
import { useAccounts, useUpdateAccount } from "@/hooks/useAccounts";
import {
  copyAccountCashbackRates,
  createCashbackCategory,
  deleteCashbackCategory,
  fetchAccountCashbackRates,
  fetchCashbackCategories,
  fetchCashbackReport,
  upsertAccountCashbackRates,
} from "@/api/cashback";
import { formatCurrency } from "@/lib/format";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import type { CashbackRounding } from "@/types";

export function CashbackPage() {
  const { t } = useTranslation();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [accountId, setAccountId] = useState("");
  const [newCategoryName, setNewCategoryName] = useState("");
  const queryClient = useQueryClient();
  const { data: accounts } = useAccounts();
  const updateAccount = useUpdateAccount();

  const nonCashAccounts = useMemo(
    () => (accounts ?? []).filter((account) => account.type !== "cash"),
    [accounts]
  );
  const selectedAccount = useMemo(
    () => nonCashAccounts.find((account) => String(account.id) === accountId) ?? null,
    [nonCashAccounts, accountId]
  );

  const categoriesQuery = useQuery({
    queryKey: ["cashback-categories"],
    queryFn: fetchCashbackCategories,
  });
  const ratesQuery = useQuery({
    queryKey: ["cashback-rates", accountId, year, month],
    queryFn: () => fetchAccountCashbackRates(Number(accountId), year, month),
    enabled: Boolean(accountId),
  });
  const reportQuery = useQuery({
    queryKey: ["cashback-report", accountId, year, month],
    queryFn: () => fetchCashbackReport(year, month, accountId ? Number(accountId) : undefined),
  });

  const createCategory = useMutation({
    mutationFn: () => createCashbackCategory({ name: newCategoryName.trim() }),
    onSuccess: () => {
      setNewCategoryName("");
      queryClient.invalidateQueries({ queryKey: ["cashback-categories"] });
    },
  });
  const removeCategory = useMutation({
    mutationFn: (id: number) => deleteCashbackCategory(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cashback-categories"] }),
  });
  const saveRates = useMutation({
    mutationFn: (rates: { cashback_category_id: number; percent: string }[]) =>
      upsertAccountCashbackRates(Number(accountId), { year, month, rates }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cashback-rates"] }),
  });
  const copyRates = useMutation({
    mutationFn: () => {
      const nextMonth = month === 12 ? 1 : month + 1;
      const nextYear = month === 12 ? year + 1 : year;
      return copyAccountCashbackRates(Number(accountId), {
        from_year: year,
        from_month: month,
        to_year: nextYear,
        to_month: nextMonth,
      });
    },
  });

  const [draftPercents, setDraftPercents] = useState<Record<number, string>>({});
  const percentFor = (categoryId: number) => {
    if (draftPercents[categoryId] !== undefined) return draftPercents[categoryId];
    const existing = ratesQuery.data?.find((rate) => rate.cashback_category_id === categoryId);
    return existing?.percent ?? "0";
  };

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("cashback.title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1">
              <MonthSelector month={month} onChange={setMonth} />
            </div>
            <div>
              <Label htmlFor="cb-year">{t("cashback.yearLabel")}</Label>
              <Input
                id="cb-year"
                type="number"
                value={year}
                onChange={(event) => setYear(Number(event.target.value))}
                className="w-28"
              />
            </div>
            <div className="min-w-0 flex-1">
              <Label htmlFor="cb-account">{t("transactions.form.accountLabel")}</Label>
              <Select id="cb-account" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
                <option value="">{t("transactions.allAccounts")}</option>
                {nonCashAccounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name} ({account.currency})
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <h3 className="text-sm font-medium text-text-primary">{t("cashback.categoriesTitle")}</h3>
            <div className="flex gap-2">
              <Input
                value={newCategoryName}
                onChange={(event) => setNewCategoryName(event.target.value)}
                placeholder={t("cashback.categoryPlaceholder")}
              />
              <Button
                type="button"
                disabled={!newCategoryName.trim() || createCategory.isPending}
                onClick={() => createCategory.mutate()}
              >
                {t("common.add")}
              </Button>
            </div>
            <ul className="divide-y divide-gridline">
              {(categoriesQuery.data ?? []).map((category) => (
                <li key={category.id} className="flex items-center justify-between py-2 text-sm">
                  <span>{category.name}</span>
                  <Button type="button" variant="ghost" onClick={() => removeCategory.mutate(category.id)}>
                    {t("common.delete")}
                  </Button>
                </li>
              ))}
            </ul>
          </div>

          {accountId && selectedAccount && (
            <div className="space-y-2">
              <Label htmlFor="cb-rounding">{t("cashback.roundingLabel")}</Label>
              <Select
                id="cb-rounding"
                value={selectedAccount.cashback_rounding}
                disabled={updateAccount.isPending}
                onChange={(event) =>
                  updateAccount.mutate({
                    id: selectedAccount.id,
                    input: { cashback_rounding: event.target.value as CashbackRounding },
                  })
                }
                className="sm:w-72"
              >
                {(["percent_floor", "base_100"] as CashbackRounding[]).map((mode) => (
                  <option key={mode} value={mode}>
                    {t(`cashback.rounding.${mode}` as TranslationKey)}
                  </option>
                ))}
              </Select>
              <p className="text-xs text-text-muted">{t("cashback.roundingHint")}</p>
            </div>
          )}

          {accountId && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-text-primary">{t("cashback.ratesTitle")}</h3>
              {(categoriesQuery.data ?? []).map((category) => (
                <div key={category.id} className="flex items-center gap-3">
                  <span className="min-w-0 flex-1 truncate text-sm">{category.name}</span>
                  <Input
                    type="number"
                    step="0.001"
                    min="0"
                    className="w-28"
                    value={percentFor(category.id)}
                    onChange={(event) =>
                      setDraftPercents((prev) => ({ ...prev, [category.id]: event.target.value }))
                    }
                  />
                  <span className="text-xs text-text-muted">%</span>
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  disabled={saveRates.isPending}
                  onClick={() => {
                    const rates = (categoriesQuery.data ?? [])
                      .map((category) => ({
                        cashback_category_id: category.id,
                        percent: percentFor(category.id) || "0",
                      }))
                      .filter((rate) => Number(rate.percent) > 0);
                    saveRates.mutate(rates);
                  }}
                >
                  {t("common.save")}
                </Button>
                <Button type="button" variant="secondary" disabled={copyRates.isPending} onClick={() => copyRates.mutate()}>
                  {t("cashback.copyToNextMonth")}
                </Button>
              </div>
            </div>
          )}

          <div className="space-y-2">
            <h3 className="text-sm font-medium text-text-primary">{t("cashback.reportTitle")}</h3>
            {reportQuery.data && (
              <>
                <p className="text-sm text-text-secondary">
                  {t("cashback.expected")}: {formatCurrency(reportQuery.data.expected_total)} ·{" "}
                  {t("cashback.actual")}: {formatCurrency(reportQuery.data.actual_total)} ·{" "}
                  {t("cashback.refundAdj")}: {formatCurrency(reportQuery.data.refund_adjustment_total)}
                </p>
                <ul className="divide-y divide-gridline text-sm">
                  {reportQuery.data.lines.map((line, index) => (
                    <li key={`${line.cashback_category_id}-${index}`} className="flex justify-between gap-3 py-2">
                      <span>{line.cashback_category_name ?? t("cashback.uncategorized")}</span>
                      <span className="tabular-nums text-text-muted">
                        {formatCurrency(line.expected_amount)} / {formatCurrency(line.actual_amount)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
