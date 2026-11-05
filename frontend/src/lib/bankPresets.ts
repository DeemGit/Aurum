// Bank-specific import presets for the CSV wizard (pages/CsvImportPage.tsx).
//
// A preset is nothing more than a pre-filled answer to the wizard's "map"
// step: which column is the date, which is the amount, what the date/amount
// formats are, and — the one thing the generic mapping can't express — which
// rows to drop (a declined card payment still shows up in the export). The
// wizard itself stays bank-agnostic: presets only feed it defaults, and the
// user can still override any of them on the map screen.
//
// Only banks whose personal-account CSV export has a known, stable header
// layout are listed. Banks that export PDF/XLSX only (Sber, Kaspi, Halyk,
// maib…) go through the generic mapping via a third-party converter instead.
import type { AmountFormat, DateFormat } from "@/lib/csv";

/** Column mapping as the wizard understands it — header *names*, not
 * indexes, so re-decoding the file under another encoding can re-resolve
 * them. Empty string = not mapped. */
export interface ImportMapping {
  date: string;
  amount: string;
  description: string;
  merchant: string;
  notes: string;
  category: string;
}

/** Matches a header cell by normalised prefix — see normalizeHeader(). A
 * prefix, not equality, because some banks put the account currency in the
 * header itself ("Сума в валюті картки (UAH)") and it changes per card. */
export type HeaderMatcher = string[];

export interface BankPreset {
  id: string;
  /** Proper name, shown as-is — bank names aren't translated. */
  label: string;
  /** Every one of these must be present for detectPreset() to pick this
   * preset. Keep it to the columns the mapping actually needs, so a bank
   * adding a trailing column doesn't break detection. */
  detect: HeaderMatcher[];
  mapping: Partial<Record<keyof ImportMapping, HeaderMatcher>>;
  dateFormat: DateFormat;
  amountFormat: AmountFormat;
  /** Rows whose `column` value fails `accept` are skipped before parsing —
   * e.g. a "Статус" column that reads FAILED for a declined payment. */
  rowFilter?: { column: HeaderMatcher; accept: (value: string) => boolean };
}

/** Lower-cased, trimmed, BOM-stripped, whitespace-collapsed header text.
 * Also folds the Latin "i" into the Cyrillic "і": monobank's Ukrainian header
 * literally reads "Дата i час операції" with a Latin i in the middle, and
 * nobody typing a matcher by hand would guess that. */
export function normalizeHeader(header: string): string {
  return header
    .replace(/^\uFEFF/, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/i/g, "і");
}

function findHeader(headers: string[], matcher: HeaderMatcher): string {
  const candidates = matcher.map(normalizeHeader);
  return headers.find((header) => candidates.some((candidate) => normalizeHeader(header).startsWith(candidate))) ?? "";
}

export const BANK_PRESETS: readonly BankPreset[] = [
  {
    // Web → Операции → «Выгрузка операций» → CSV. Semicolon-separated, every
    // field quoted, comma decimal mark, dates carry a time of day.
    // "Сумма в валюте счёта" is what the account balance moved by (foreign
    // purchases keep the original amount in "Сумма операции"). Older exports
    // used "Сумма платежа" — kept as amount fallback for manual preset pick.
    id: "tbank",
    label: "Т-Банк",
    detect: [["дата операции"], ["сумма в валюте счёта"], ["описание"], ["статус"]],
    mapping: {
      date: ["дата операции"],
      amount: ["сумма в валюте счёта", "сумма платежа"],
      description: ["описание"],
      category: ["ваша категория"],
      notes: ["сообщение"],
    },
    dateFormat: "DD.MM.YYYY",
    amountFormat: "comma-decimal",
    // Real exports use Cyrillic «Ок»; older samples used Latin "OK".
    rowFilter: {
      column: ["статус"],
      accept: (value) => {
        const status = value.trim().toUpperCase();
        return status === "OK" || status === "ОК";
      },
    },
  },
  {
    // App → card → Виписка → CSV, Ukrainian UI language. Comma-separated,
    // UTF-8, dot decimal mark, empty cells written as an em dash ("—").
    // The amount header embeds the card currency, hence the prefix match.
    id: "monobank",
    label: "monobank",
    detect: [["дата і час операції"], ["деталі операції"], ["сума в валюті картки"]],
    mapping: {
      date: ["дата і час операції"],
      amount: ["сума в валюті картки"],
      description: ["деталі операції"],
    },
    dateFormat: "DD.MM.YYYY",
    amountFormat: "dot-decimal",
  },
  {
    // next.privat24.ua → card → Виписки → CSV. Date and time come in
    // separate columns, so the plain date parses as-is; the amount in the
    // card's currency is what the balance moved by.
    id: "privatbank",
    label: "ПриватБанк",
    detect: [["дата"], ["опис операції"], ["сума в валюті картки"]],
    mapping: {
      date: ["дата"],
      amount: ["сума в валюті картки"],
      description: ["опис операції"],
      category: ["категорія"],
    },
    dateFormat: "DD.MM.YYYY",
    amountFormat: "auto",
  },
];

export function findPreset(id: string): BankPreset | null {
  return BANK_PRESETS.find((preset) => preset.id === id) ?? null;
}

/** The first preset whose every `detect` matcher finds a header. Order in
 * BANK_PRESETS matters only if two banks ever share a header set. */
export function detectPreset(headers: string[]): BankPreset | null {
  return BANK_PRESETS.find((preset) => preset.detect.every((matcher) => findHeader(headers, matcher) !== "")) ?? null;
}

/** Resolves a preset's matchers against the actual header row. Fields the
 * preset doesn't cover fall back to `fallback` (the wizard's generic
 * header guesses), so a preset only has to describe what it knows. */
export function applyPresetMapping(preset: BankPreset, headers: string[], fallback: ImportMapping): ImportMapping {
  const resolved = { ...fallback };
  (Object.keys(preset.mapping) as (keyof ImportMapping)[]).forEach((field) => {
    const matcher = preset.mapping[field];
    if (matcher) resolved[field] = findHeader(headers, matcher);
  });
  return resolved;
}

/** When `preset.rowFilter` says this row is not a real transaction, returns
 * the offending cell value (for the "skipped because…" message); null means
 * keep the row. Also null when the preset has no filter or its column is
 * missing from the header row — an absent status column is not a reason
 * to drop data. */
export function rowFilterRejection(preset: BankPreset | null, headers: string[], cells: string[]): string | null {
  if (!preset?.rowFilter) return null;
  const idx = headers.indexOf(findHeader(headers, preset.rowFilter.column));
  if (idx < 0) return null;
  const value = cells[idx] ?? "";
  return preset.rowFilter.accept(value) ? null : value.trim();
}
