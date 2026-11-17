import { Card } from "@/components/ui/Card";
import { formatCurrency, formatSignedCurrency } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";

interface PlannedBalanceCardProps {
  plannedIncome: number | string;
  plannedExpenses: number | string;
  /** Forecast: net + planned_income − planned_expenses. */
  projectedBalance: number;
  isLoading?: boolean;
}

export function PlannedBalanceCard({
  plannedIncome,
  plannedExpenses,
  projectedBalance,
  isLoading = false,
}: PlannedBalanceCardProps) {
  const { t } = useTranslation();
  const projectedTone =
    projectedBalance >= 0 ? "text-success" : "text-danger";

  return (
    <Card className="p-4 sm:p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        {t("dashboard.plannedCardTitle")}
      </p>
      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <p className="text-xs text-text-muted">{t("dashboard.statPlannedIncomeLabel")}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-success sm:text-2xl">
            {isLoading ? "…" : formatCurrency(plannedIncome)}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">{t("dashboard.statPlannedExpensesLabel")}</p>
          <p className="mt-1 text-xl font-semibold tabular-nums text-danger sm:text-2xl">
            {isLoading ? "…" : formatCurrency(plannedExpenses)}
          </p>
        </div>
        <div>
          <p className="text-xs text-text-muted">{t("dashboard.projectedBalanceLabel")}</p>
          <p className={cn("mt-1 text-xl font-semibold tabular-nums sm:text-2xl", projectedTone)}>
            {isLoading ? "…" : formatSignedCurrency(projectedBalance)}
          </p>
          <p className="mt-1 text-xs text-text-muted">{t("dashboard.projectedBalanceCaption")}</p>
        </div>
      </div>
    </Card>
  );
}
