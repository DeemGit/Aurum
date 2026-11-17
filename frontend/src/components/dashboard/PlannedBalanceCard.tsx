import { ChevronDown, ChevronRight } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
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
  const [collapsed, setCollapsed] = useLocalStorageState("aurum:planned-card-collapsed", false);
  const projectedTone = projectedBalance >= 0 ? "text-success" : "text-danger";

  return (
    <Card className="p-4 sm:p-5">
      <button
        type="button"
        className="flex w-full items-center gap-2 text-left"
        aria-expanded={!collapsed}
        aria-label={collapsed ? t("common.expand") : t("common.collapse")}
        onClick={() => setCollapsed(!collapsed)}
      >
        {collapsed ? (
          <ChevronRight size={16} className="shrink-0 text-text-muted" />
        ) : (
          <ChevronDown size={16} className="shrink-0 text-text-muted" />
        )}
        <span className="min-w-0 flex-1 text-xs font-semibold uppercase tracking-wide text-text-muted">
          {t("dashboard.plannedCardTitle")}
        </span>
        {collapsed && (
          <span className={cn("shrink-0 text-sm font-semibold tabular-nums", projectedTone)}>
            {isLoading ? "…" : formatSignedCurrency(projectedBalance)}
          </span>
        )}
      </button>

      {!collapsed && (
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
      )}
    </Card>
  );
}
