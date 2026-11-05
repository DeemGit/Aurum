import { useEffect, useMemo, useState } from "react";
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
  updateCashbackCategory,
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
  const [newCategoryPercent, setNewCategoryPercent] = useState("");
  const [draftNames, setDraftNames] = useState<Record<number, string>>({});
  const [draftPercents, setDraftPercents] = useState<Record<number, string>>({});
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
  const accountFilterId = accountId ? Number(accountId) : undefined;

  const categoriesQuery = useQuery({
    queryKey: ["cashback-categories", accountId || "all"],
    queryFn: () => fetchCashbackCategories(accountFilterId),
  });

  const ratesQuery = useQuery({
    queryKey: ["cashback-rates", accountId, year, month],
    queryFn: () => fetchAccountCashbackRates(Number(accountId), year, month),
    enabled: Boolean(accountId),
  });

  // For "all accounts" view: load rates per account for the month.
  const allRatesQueries = useQuery({
    queryKey: ["cashback-rates-all", year, month, nonCashAccounts.map((a) => a.id).join(",")],
    queryFn: async () => {
      const chunks = await Promise.all(
        nonCashAccounts.map(async (account) => ({
          account,
          rates: await fetchAccountCashbackRates(account.id, year, month),
        }))
      );
      return chunks.flatMap(({ account, rates }) =>
        rates.map((rate) => ({
          accountId: account.id,
          accountName: account.name,
          categoryId: rate.cashback_category_id,
          categoryName: rate.cashback_category?.name ?? `#${rate.cashback_category_id}`,
          percent: rate.percent,
        }))
      );
    },
    enabled: !accountId && nonCashAccounts.length > 0,
  });

  const reportQuery = useQuery({
    queryKey: ["cashback-report", accountId, year, month],
    queryFn: () => fetchCashbackReport(year, month, accountId ? Number(accountId) : undefined),
  });

  useEffect(() => {
    setDraftNames({});
    setDraftPercents({});
  }, [accountId, year, month, categoriesQuery.dataUpdatedAt, ratesQuery.dataUpdatedAt]);

  const invalidateCashback = () => {
    queryClient.invalidateQueries({ queryKey: ["cashback-categories"] });
    queryClient.invalidateQueries({ queryKey: ["cashback-rates"] });
    queryClient.invalidateQueries({ queryKey: ["cashback-rates-all"] });
    queryClient.invalidateQueries({ queryKey: ["cashback-report"] });
  };

  const createCategory = useMutation({
    mutationFn: async () => {
      const category = await createCashbackCategory({
        account_id: Number(accountId),
        name: newCategoryName.trim(),
      });
      const percent = newCategoryPercent.trim();
      if (percent && Number(percent) > 0) {
        const existing = (ratesQuery.data ?? []).map((rate) => ({
          cashback_category_id: rate.cashback_category_id,
          percent: rate.percent,
        }));
        await upsertAccountCashbackRates(Number(accountId), {
          year,
          month,
          rates: [...existing, { cashback_category_id: category.id, percent }],
        });
      }
      return category;
    },
    onSuccess: () => {
      setNewCategoryName("");
      setNewCategoryPercent("");
      invalidateCashback();
    },
  });

  const saveCategoryName = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => updateCashbackCategory(id, { name }),
    onSuccess: invalidateCashback,
  });

  const removeCategory = useMutation({
    mutationFn: (id: number) => deleteCashbackCategory(id),
    onSuccess: invalidateCashback,
  });

  const saveRates = useMutation({
    mutationFn: (rates: { cashback_category_id: number; percent: string }[]) =>
      upsertAccountCashbackRates(Number(accountId), { year, month, rates }),
    onSuccess: invalidateCashback,
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
    onSuccess: invalidateCashback,
  });

  const nameFor = (categoryId: number, fallback: string) =>
    draftNames[categoryId] !== undefined ? draftNames[categoryId] : fallback;

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

          {!accountId && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-text-primary">{t("cashback.ratesTitle")}</h3>
              <p className="text-xs text-text-muted">{t("cashback.allAccountsReadonly")}</p>
              <ul className="divide-y divide-gridline text-sm">
                {(allRatesQueries.data ?? []).map((row) => (
                  <li
                    key={`${row.accountId}-${row.categoryId}`}
                    className="flex flex-col gap-1 py-2 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <span className="min-w-0 truncate text-text-primary">
                      {row.accountName} · {row.categoryName}
                    </span>
                    <span className="tabular-nums text-text-muted">{row.percent}%</span>
                  </li>
                ))}
                {(allRatesQueries.data ?? []).length === 0 && (
                  <li className="py-2 text-text-muted">{t("cashback.selectAccountHint")}</li>
                )}
              </ul>
            </div>
          )}

          {accountId && selectedAccount && (
            <>
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

              <div className="space-y-2">
                <h3 className="text-sm font-medium text-text-primary">{t("cashback.ratesTitle")}</h3>
                <p className="text-xs text-text-muted">
                  {selectedAccount.name} · {t("cashback.colAccount")}
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input
                    value={newCategoryName}
                    onChange={(event) => setNewCategoryName(event.target.value)}
                    placeholder={t("cashback.categoryPlaceholder")}
                    className="min-w-0 flex-1"
                  />
                  <Input
                    type="number"
                    step="0.001"
                    min="0"
                    value={newCategoryPercent}
                    onChange={(event) => setNewCategoryPercent(event.target.value)}
                    placeholder={t("cashback.percentPlaceholder")}
                    className="w-full sm:w-24"
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
                    <li key={category.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center">
                      <Input
                        value={nameFor(category.id, category.name)}
                        onChange={(event) =>
                          setDraftNames((prev) => ({ ...prev, [category.id]: event.target.value }))
                        }
                        onBlur={() => {
                          const next = nameFor(category.id, category.name).trim();
                          if (next && next !== category.name) {
                            saveCategoryName.mutate({ id: category.id, name: next });
                          }
                        }}
                        className="min-w-0 flex-1"
                        aria-label={t("cashback.colCategory")}
                      />
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          step="0.001"
                          min="0"
                          className="w-24"
                          value={percentFor(category.id)}
                          onChange={(event) =>
                            setDraftPercents((prev) => ({ ...prev, [category.id]: event.target.value }))
                          }
                          aria-label={t("cashback.colPercent")}
                        />
                        <span className="text-xs text-text-muted">%</span>
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() => removeCategory.mutate(category.id)}
                        >
                          {t("common.delete")}
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>

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
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={copyRates.isPending}
                    onClick={() => copyRates.mutate()}
                  >
                    {t("cashback.copyToNextMonth")}
                  </Button>
                </div>
              </div>
            </>
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
