import { useState } from "react";
import { Check, Pencil, Plus, StepForward, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { TodoFormModal } from "@/components/todos/TodoFormModal";
import {
  useCompleteTodo,
  useDeleteTodo,
  useStepTodo,
  useTodos,
} from "@/hooks/useTodos";
import { formatCurrency, getIntlLocale } from "@/lib/format";
import { useTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { TodoItem } from "@/types";

function formatDueDate(isoDate: string): string {
  return new Intl.DateTimeFormat(getIntlLocale(), {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(`${isoDate}T00:00:00`));
}

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function isMuted(item: TodoItem, today: string): boolean {
  if (item.deleted_at || item.completed_at) return true;
  return item.due_date < today;
}

/** Derive completed steps from percent when step_count is set. */
function currentStep(progressPercent: number, stepCount: number): number {
  if (progressPercent >= 100) return stepCount;
  if (progressPercent <= 0) return 0;
  return Math.min(stepCount, Math.round((progressPercent * stepCount) / 100));
}

export function TodosPage() {
  const { t } = useTranslation();
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const { data: items, isLoading } = useTodos(includeDeleted);
  const deleteTodo = useDeleteTodo();
  const completeTodo = useCompleteTodo();
  const stepTodo = useStepTodo();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<TodoItem | null>(null);
  const today = todayIso();

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(item: TodoItem) {
    setEditing(item);
    setFormOpen(true);
  }

  function handleDelete(item: TodoItem) {
    const message = item.deleted_at
      ? t("todo.confirmPurge", { title: item.title })
      : t("todo.confirmDelete", { title: item.title });
    if (window.confirm(message)) {
      deleteTodo.mutate(item.id);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader className="flex-wrap gap-3">
          <CardTitle>{t("nav.todos")}</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={() => setIncludeDeleted((prev) => !prev)}
            >
              {includeDeleted ? t("todo.hideDeleted") : t("todo.showDeleted")}
            </Button>
            <Button onClick={openCreate}>
              <Plus size={16} />
              {t("common.add")}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="py-10 text-center text-sm text-text-muted">{t("common.loading")}</p>
          ) : !items || items.length === 0 ? (
            <p className="py-10 text-center text-sm text-text-muted">{t("todo.empty")}</p>
          ) : (
            <ul className="divide-y divide-gridline">
              {items.map((item) => {
                const muted = isMuted(item, today);
                // Step / complete — only while still open.
                const canMutate = !item.deleted_at && !item.completed_at;
                // Edit and soft-delete are allowed for completed items.
                const canEdit = !item.deleted_at;
                // Soft-deleted rows can be purged permanently (shown with include_deleted).
                const canPurge = !!item.deleted_at;
                return (
                  <li
                    key={item.id}
                    className={cn("py-3", muted && "opacity-50")}
                  >
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                          <span className="text-sm font-medium text-text-primary">{item.title}</span>
                          <span className="text-xs text-text-muted">{formatDueDate(item.due_date)}</span>
                          {item.due_date < today && !item.completed_at && !item.deleted_at && (
                            <span className="text-xs text-danger">{t("todo.overdue")}</span>
                          )}
                          {item.deleted_at && (
                            <span className="text-xs text-text-muted">{t("todo.deleted")}</span>
                          )}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-muted">
                          <span>
                            {item.kind === "income" ? t("todo.kind.income") : t("todo.kind.expense")}
                          </span>
                          {item.amount != null && (
                            <span className="tabular-nums text-text-primary">
                              {formatCurrency(item.amount)}
                            </span>
                          )}
                          <span className="tabular-nums">
                            {t("todo.progressLabel")}:{" "}
                            {item.step_count != null
                              ? t("todo.progressWithSteps", {
                                  percent: item.progress_percent,
                                  current: currentStep(item.progress_percent, item.step_count),
                                  total: item.step_count,
                                })
                              : t("todo.progress", { percent: item.progress_percent })}
                          </span>
                          {!item.count_in_dashboard && (
                            <span className="rounded bg-surface-2 px-1 py-0.5">
                              {t("todo.notInDashboard")}
                            </span>
                          )}
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
                          <span
                            className="block h-full rounded-full bg-success"
                            style={{ width: `${Math.min(100, item.progress_percent)}%` }}
                          />
                        </div>
                      </div>
                      <div className="flex shrink-0 flex-wrap gap-1">
                        {canMutate && item.step_count != null && (
                          <Button
                            type="button"
                            variant="secondary"
                            className="h-8 px-2.5 text-xs"
                            onClick={() => stepTodo.mutate(item.id)}
                            disabled={stepTodo.isPending}
                          >
                            <StepForward size={14} />
                            {t("todo.step")}
                          </Button>
                        )}
                        {canMutate && (
                          <Button
                            type="button"
                            variant="secondary"
                            className="h-8 px-2.5 text-xs"
                            onClick={() => completeTodo.mutate(item.id)}
                            disabled={completeTodo.isPending}
                          >
                            <Check size={14} />
                            {t("todo.complete")}
                          </Button>
                        )}
                        {canEdit && (
                          <button
                            type="button"
                            aria-label={t("common.edit")}
                            onClick={() => openEdit(item)}
                            className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-text-primary"
                          >
                            <Pencil size={15} />
                          </button>
                        )}
                        {(canEdit || canPurge) && (
                          <button
                            type="button"
                            aria-label={t("common.delete")}
                            onClick={() => handleDelete(item)}
                            className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-danger"
                          >
                            <Trash2 size={15} />
                          </button>
                        )}
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </CardContent>
      </Card>

      <TodoFormModal open={formOpen} onClose={() => setFormOpen(false)} todo={editing} />
    </div>
  );
}
