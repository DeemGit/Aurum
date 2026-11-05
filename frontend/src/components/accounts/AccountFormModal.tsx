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

const EMPTY_FORM = { name: "", type: "checking" as AccountType, currency: getCurrency() };

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
        ? { name: account.name, type: account.type, currency: account.currency }
        : { ...EMPTY_FORM, currency: getCurrency() }
    );
    setError(null);
  }, [open, account]);

  const isSaving = createAccount.isPending || updateAccount.isPending;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    try {
      if (account) {
        // Currency is immutable after create — only name/type go on update.
        await updateAccount.mutateAsync({ id: account.id, input: { name: form.name, type: form.type } });
      } else {
        await createAccount.mutateAsync(form);
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
