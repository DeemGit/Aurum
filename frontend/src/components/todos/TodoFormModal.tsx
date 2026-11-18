import { useEffect, useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import { useCreateTodo, useUpdateTodo } from "@/hooks/useTodos";
import { useTranslation } from "@/lib/i18n";
import type { TodoItem, TodoKind } from "@/types";

interface TodoFormModalProps {
  open: boolean;
  onClose: () => void;
  todo?: TodoItem | null;
}

interface FormState {
  title: string;
  due_date: string;
  amount: string;
  kind: TodoKind;
  step_count: string;
  count_in_dashboard: boolean;
}

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

const EMPTY_FORM: FormState = {
  title: "",
  due_date: todayIso(),
  amount: "",
  kind: "expense",
  step_count: "",
  count_in_dashboard: true,
};

export function TodoFormModal({ open, onClose, todo }: TodoFormModalProps) {
  const { t } = useTranslation();
  const createTodo = useCreateTodo();
  const updateTodo = useUpdateTodo();

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (todo) {
      setForm({
        title: todo.title,
        due_date: todo.due_date,
        amount: todo.amount ?? "",
        kind: todo.kind,
        step_count: todo.step_count != null ? String(todo.step_count) : "",
        count_in_dashboard: todo.count_in_dashboard,
      });
    } else {
      setForm({ ...EMPTY_FORM, due_date: todayIso() });
    }
    setError(null);
  }, [open, todo]);

  const isSaving = createTodo.isPending || updateTodo.isPending;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const stepRaw = form.step_count.trim();
    const step_count = stepRaw === "" ? null : Number(stepRaw);
    if (step_count !== null && (!Number.isInteger(step_count) || step_count < 1)) {
      setError(t("todo.form.saveError"));
      return;
    }

    const input = {
      title: form.title.trim(),
      due_date: form.due_date,
      amount: form.amount.trim() === "" ? null : form.amount.trim(),
      kind: form.kind,
      step_count,
      // Progress notes never feed dashboard planned_* totals.
      count_in_dashboard: form.kind === "progress" ? false : form.count_in_dashboard,
    };

    try {
      if (todo) {
        await updateTodo.mutateAsync({ id: todo.id, input });
      } else {
        await createTodo.mutateAsync(input);
      }
      onClose();
    } catch {
      setError(t("todo.form.saveError"));
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={todo ? t("todo.form.editTitle") : t("todo.form.newTitle")}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <Label htmlFor="todo-title">{t("todo.form.titleLabel")}</Label>
          <Input
            id="todo-title"
            required
            placeholder={t("todo.form.titlePlaceholder")}
            value={form.title}
            onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="todo-due">{t("todo.form.dueDateLabel")}</Label>
            <Input
              id="todo-due"
              type="date"
              required
              value={form.due_date}
              onChange={(event) => setForm((prev) => ({ ...prev, due_date: event.target.value }))}
            />
          </div>
          <div>
            <Label htmlFor="todo-amount">{t("todo.form.amountLabel")}</Label>
            <Input
              id="todo-amount"
              type="number"
              step="0.01"
              min="0.01"
              value={form.amount}
              onChange={(event) => setForm((prev) => ({ ...prev, amount: event.target.value }))}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="todo-kind">{t("todo.form.kindLabel")}</Label>
            <select
              id="todo-kind"
              className="h-9 w-full rounded-lg border border-border bg-surface-1 px-3 text-sm text-text-primary"
              value={form.kind}
              onChange={(event) => {
                const kind = event.target.value as TodoKind;
                setForm((prev) => ({
                  ...prev,
                  kind,
                  count_in_dashboard: kind === "progress" ? false : prev.count_in_dashboard,
                }));
              }}
            >
              <option value="expense">{t("todo.kind.expense")}</option>
              <option value="income">{t("todo.kind.income")}</option>
              <option value="progress">{t("todo.kind.progress")}</option>
            </select>
          </div>
          <div>
            <Label htmlFor="todo-steps">{t("todo.form.stepCountLabel")}</Label>
            <Input
              id="todo-steps"
              type="number"
              min="1"
              step="1"
              value={form.step_count}
              onChange={(event) => setForm((prev) => ({ ...prev, step_count: event.target.value }))}
            />
            <p className="mt-1 text-xs text-text-muted">{t("todo.form.stepCountHint")}</p>
          </div>
        </div>

        {form.kind !== "progress" && (
          <label className="flex items-center gap-2 text-sm text-text-primary">
            <input
              type="checkbox"
              className="h-4 w-4 rounded border-border"
              checked={form.count_in_dashboard}
              onChange={(event) =>
                setForm((prev) => ({ ...prev, count_in_dashboard: event.target.checked }))
              }
            />
            {t("todo.form.countInDashboard")}
          </label>
        )}

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose} disabled={isSaving}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={isSaving}>
            {isSaving ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
