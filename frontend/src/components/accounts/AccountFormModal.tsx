import { useEffect, useState } from "react";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Input, Label, Select } from "@/components/ui/Input";
import { useCreateAccount, useUpdateAccount } from "@/hooks/useAccounts";
import { CURRENCIES, getCurrencyLabel } from "@/lib/currency";
import { getCurrency, useTranslation, type TranslationKey } from "@/lib/i18n";
import type { Account, AccountType } from "@/types";

interface AccountFormModalProps {
  open: boolean;
  onClose: () => void;
  account?: Account | null;
}

const ACCOUNT_TYPES: AccountType[] = ["checking", "debit_card", "savings", "credit_card", "cash", "investment", "other"];

const EMPTY_FORM = {
  name: "",
  type: "checking" as AccountType,
  currency: getCurrency(),
  statement_day: "25",
  payment_day: "18",
  grace_period_days: "55",
};

export function AccountFormModal({ open, onClose, account }: AccountFormModalProps) {
  const { t, language } = useTranslation();
  const createAccount = useCreateAccount();
  const updateAccount = useUpdateAccount();

  const [form, setForm] = useState(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(
      account
        ? {
            name: account.name,
            type: account.type,
            currency: account.currency,
            statement_day: account.statement_day != null ? String(account.statement_day) : "25",
            payment_day: account.payment_day != null ? String(account.payment_day) : "18",
            grace_period_days: account.grace_period_days != null ? String(account.grace_period_days) : "55",
          }
        : { ...EMPTY_FORM, currency: getCurrency() }
    );
    setError(null);
  }, [open, account]);

  const isSaving = createAccount.isPending || updateAccount.isPending;
  const isCredit = form.type === "credit_card";

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const cycle = isCredit
      ? {
          statement_day: Number(form.statement_day),
          payment_day: Number(form.payment_day),
          grace_period_days: Number(form.grace_period_days),
        }
      : {
          statement_day: null,
          payment_day: null,
          grace_period_days: null,
        };

    try {
      if (account) {
        // Currency is immutable after create — only name/type/cycle go on update.
        await updateAccount.mutateAsync({
          id: account.id,
          input: { name: form.name, type: form.type, ...cycle },
        });
      } else {
        await createAccount.mutateAsync({
          name: form.name,
          type: form.type,
          currency: form.currency,
          ...cycle,
        });
      }
      onClose();
    } catch {
      setError(t("account.form.saveError"));
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={account ? t("account.form.editTitle") : t("account.form.newTitle")}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <Label htmlFor="account-name">{t("account.form.nameLabel")}</Label>
          <Input
            id="account-name"
            required
            placeholder={t("account.form.namePlaceholder")}
            value={form.name}
            onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          />
        </div>

        <div>
          <Label htmlFor="account-type">{t("account.form.typeLabel")}</Label>
          <Select
            id="account-type"
            value={form.type}
            onChange={(event) => setForm((prev) => ({ ...prev, type: event.target.value as AccountType }))}
          >
            {ACCOUNT_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`account.type.${type}` as TranslationKey)}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <Label htmlFor="account-currency">{t("account.form.currencyLabel")}</Label>
          <Select
            id="account-currency"
            value={form.currency}
            disabled={Boolean(account)}
            onChange={(event) => setForm((prev) => ({ ...prev, currency: event.target.value }))}
          >
            {CURRENCIES.map((currency) => (
              <option key={currency.code} value={currency.code}>
                {getCurrencyLabel(currency.code, language)}
              </option>
            ))}
          </Select>
          {account && <p className="mt-1 text-xs text-text-muted">{t("account.form.currencyImmutable")}</p>}
        </div>

        {isCredit && (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="statement-day">{t("account.form.statementDayLabel")}</Label>
              <Input
                id="statement-day"
                type="number"
                required
                min={1}
                max={28}
                value={form.statement_day}
                onChange={(event) => setForm((prev) => ({ ...prev, statement_day: event.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="payment-day">{t("account.form.paymentDayLabel")}</Label>
              <Input
                id="payment-day"
                type="number"
                required
                min={1}
                max={28}
                value={form.payment_day}
                onChange={(event) => setForm((prev) => ({ ...prev, payment_day: event.target.value }))}
              />
            </div>
            <div>
              <Label htmlFor="grace-days">{t("account.form.gracePeriodLabel")}</Label>
              <Input
                id="grace-days"
                type="number"
                required
                min={1}
                max={120}
                value={form.grace_period_days}
                onChange={(event) => setForm((prev) => ({ ...prev, grace_period_days: event.target.value }))}
              />
            </div>
            <p className="text-xs text-text-muted sm:col-span-3">{t("account.form.creditCycleHint")}</p>
          </div>
        )}

        {error && <p className="text-sm text-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
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
