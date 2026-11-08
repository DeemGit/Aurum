import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Upload } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input, Label, Select } from "@/components/ui/Input";
import { useAccounts } from "@/hooks/useAccounts";
import { useCategories } from "@/hooks/useCategories";
import {
  useAttachImportHash,
  useBulkCreateTransactions,
  useImportLinkCandidates,
  useTransactionsForDuplicateCheck,
} from "@/hooks/useTransactions";
import { convertAlfaHtmlStatement, convertGpbHtmlStatement } from "@/api/transactions";
import { translateCategoryName } from "@/lib/categoryLabels";
import {
  BANK_PRESETS,
  applyAmountSign,
  amountSignColumnValue,
  applyPresetMapping,
  detectPreset,
  findPreset,
  rowFilterRejection,
  type BankPreset,
  type ImportMapping,
} from "@/lib/bankPresets";
import {
  AMOUNT_FORMATS,
  DATE_FORMATS,
  computeImportHash,
  parseAmount,
  parseCsv,
  parseDateTimeWithFormat,
  parseDateWithFormat,
  toOccurredAtIso,
  transactionDedupeKey,
  type AmountFormat,
  type DateFormat,
} from "@/lib/csv";
import { formatCurrency, formatTransactionDate } from "@/lib/format";
import { ApiError } from "@/api/client";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import type { TransactionInput } from "@/types";

type Step = "upload" | "map" | "preview";
type UploadSource = "csv" | "gpb-html" | "alfa-html";

const NONE = "";

function todayLocalIso() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

// WHATWG encoding labels TextDecoder understands. UTF-8 covers most modern
// exports; the rest are here because bank CSVs — especially older or
// Russian-bank ones — are routinely still in a legacy Windows codepage, and
// decoding those as UTF-8 silently turns every non-ASCII character into
// mojibake instead of failing loudly.
const ENCODINGS = ["utf-8", "windows-1251", "windows-1252", "koi8-r"] as const;
type Encoding = (typeof ENCODINGS)[number];

// Header names, not indexes — see lib/bankPresets.ts's ImportMapping.
type Mapping = ImportMapping;

// "auto" lets detectPreset() pick a bank profile from the header row; a
// preset id pins one regardless of what the headers look like.
const PRESET_AUTO = "auto";

interface SkippedRow {
  row: number;
  reason: string;
}

// Best-effort auto-mapping by common header names — whatever it gets wrong,
// the user corrects on the map screen.
const HEADER_GUESSES: Record<keyof Mapping, string[]> = {
  date: ["date", "дата"],
  amount: ["amount", "сумма"],
  description: ["description", "описание", "назначение платежа"],
  merchant: ["merchant", "payee", "получатель"],
  notes: ["notes", "заметка", "примечание"],
  category: ["category", "категория"],
};

function guessMapping(headerRow: string[]): Mapping {
  const guess = (candidates: string[]) => headerRow.find((h) => candidates.includes(h.trim().toLowerCase())) ?? "";
  return {
    date: guess(HEADER_GUESSES.date),
    amount: guess(HEADER_GUESSES.amount),
    description: guess(HEADER_GUESSES.description),
    merchant: guess(HEADER_GUESSES.merchant),
    notes: guess(HEADER_GUESSES.notes),
    category: guess(HEADER_GUESSES.category),
  };
}

/** The bank profile in force for a given header row: the pinned one when
 * the user picked a bank, otherwise whatever the headers match (or null —
 * plain generic mapping). Pure, so both the file handler and the
 * header-change effect below resolve it the same way. */
function resolvePreset(headers: string[], presetChoice: string): BankPreset | null {
  return presetChoice === PRESET_AUTO ? detectPreset(headers) : findPreset(presetChoice);
}

/** Map-step defaults for a header row: the preset's answers where it has
 * them, the generic header guesses everywhere else. */
function resolveDefaults(headers: string[], preset: BankPreset | null): { mapping: Mapping; dateFormat: DateFormat; amountFormat: AmountFormat } {
  const guessed = guessMapping(headers);
  if (!preset) return { mapping: guessed, dateFormat: "YYYY-MM-DD", amountFormat: "auto" };
  return {
    mapping: applyPresetMapping(preset, headers, guessed),
    dateFormat: preset.dateFormat,
    amountFormat: preset.amountFormat,
  };
}

export function CsvImportPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data: accounts } = useAccounts();
  const { data: categories } = useCategories();
  const bulkCreate = useBulkCreateTransactions();
  const attachImportHashMutation = useAttachImportHash();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [accountId, setAccountId] = useState("");
  const [step, setStep] = useState<Step>("upload");
  const [uploadSource, setUploadSource] = useState<UploadSource>("csv");
  const [fileName, setFileName] = useState("");
  const [fileBuffer, setFileBuffer] = useState<ArrayBuffer | null>(null);
  const [encoding, setEncoding] = useState<Encoding>("utf-8");
  const [presetChoice, setPresetChoice] = useState<string>(PRESET_AUTO);
  const [mapping, setMapping] = useState<Mapping>({ date: "", amount: "", description: "", merchant: "", notes: "", category: "" });
  const [dateFormat, setDateFormat] = useState<DateFormat>("YYYY-MM-DD");
  const [amountFormat, setAmountFormat] = useState<AmountFormat>("auto");
  const [parseError, setParseError] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [createdCount, setCreatedCount] = useState<number | null>(null);
  const [gpbHtml, setGpbHtml] = useState("");
  const [alfaHtml, setAlfaHtml] = useState("");
  const [htmlToday, setHtmlToday] = useState(todayLocalIso);
  const [gpbConverting, setGpbConverting] = useState(false);
  const [alfaConverting, setAlfaConverting] = useState(false);
  const [convertedCsv, setConvertedCsv] = useState<string | null>(null);
  const [selectedIndexes, setSelectedIndexes] = useState<Set<number>>(() => new Set());
  const selectAllRef = useRef<HTMLInputElement>(null);

  // Re-decoded whenever `encoding` changes, so picking a different encoding
  // on the map screen (because the auto-detected guess came out wrong)
  // re-parses the same upload without asking the user to re-select the file.
  const { headers, dataRows } = useMemo(() => {
    if (!fileBuffer) return { headers: [] as string[], dataRows: [] as string[][] };
    const text = new TextDecoder(encoding).decode(fileBuffer);
    const rows = parseCsv(text);
    if (rows.length < 2) return { headers: [] as string[], dataRows: [] as string[][] };
    const [headerRow, ...rest] = rows;
    return { headers: headerRow, dataRows: rest };
  }, [fileBuffer, encoding]);

  const activePreset = useMemo(() => resolvePreset(headers, presetChoice), [headers, presetChoice]);

  // Owns mapping initialisation, keyed on the header row's *contents* and
  // the chosen bank profile.
  // Changing the encoding re-decodes that row, and a column picked under the
  // previous encoding then names a header that no longer exists:
  // headers.indexOf() returns -1, the dropdown renders blank while
  // mappingComplete still reports "ready", and every row gets skipped as an
  // unparseable date. Re-guessing against the new names is the only sane
  // reading of a mapping whose columns are all gone. When the decoded
  // headers come out identical (an all-ASCII header row survives every
  // encoding here), the key doesn't change, this doesn't run, and manual
  // column picks stay put. Switching the bank profile re-runs it on
  // purpose: the whole point of picking a bank is to replace the mapping.
  // JSON.stringify, not join(): joining on a separator would read
  // ["ab","c"] and ["a","bc"] as one and the same header row.
  const headersKey = JSON.stringify(headers);
  useEffect(() => {
    if (headers.length === 0) return;
    const preset = resolvePreset(headers, presetChoice);
    const defaults = resolveDefaults(headers, preset);
    setMapping(defaults.mapping);
    // Formats are only overwritten when a bank profile dictates them; with
    // no profile, a date format the user picked by hand survives an
    // encoding switch (the fresh-file reset lives in handleFileSelected).
    if (preset) {
      setDateFormat(defaults.dateFormat);
      setAmountFormat(defaults.amountFormat);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [headersKey, presetChoice]);

  const categoryLookup = useMemo(() => {
    const map: Record<"income" | "expense", Map<string, number>> = { income: new Map(), expense: new Map() };
    for (const category of categories ?? []) {
      map[category.kind].set(category.name.trim().toLowerCase(), category.id);
      map[category.kind].set(translateCategoryName(category.name).trim().toLowerCase(), category.id);
    }
    return map;
  }, [categories]);

  function resolveType(amount: number): "income" | "expense" {
    return amount < 0 ? "expense" : "income";
  }

  /** First non-empty raw value under `headerName`, shown next to a mapping
   * dropdown so the user can confirm they picked the right column before
   * committing to a full preview — a bank's own header names (or a header
   * row that's just "Column1", "Column2"…) aren't always self-explanatory. */
  function sampleValue(headerName: string): string {
    if (!headerName) return "";
    const idx = headers.indexOf(headerName);
    if (idx < 0) return "";
    const row = dataRows.find((cells) => (cells[idx] ?? "").trim() !== "");
    return (row?.[idx] ?? "").trim();
  }

  // Bounds the duplicate-check query (see useTransactionsForDuplicateCheck
  // below) to the date range actually present in the file, instead of every
  // transaction ever recorded on the account.
  const dateBounds = useMemo(() => {
    if (step !== "preview" || !mapping.date) return null;
    const dateIdx = headers.indexOf(mapping.date);
    if (dateIdx < 0) return null;
    let min: string | null = null;
    let max: string | null = null;
    for (const cells of dataRows) {
      const iso = parseDateWithFormat(cells[dateIdx] ?? "", dateFormat);
      if (!iso) continue;
      if (min === null || iso < min) min = iso;
      if (max === null || iso > max) max = iso;
    }
    return min && max ? { min, max } : null;
  }, [step, headers, dataRows, mapping.date, dateFormat]);

  const existingTransactions = useTransactionsForDuplicateCheck(
    accountId ? Number(accountId) : null,
    dateBounds?.min ?? null,
    dateBounds?.max ?? null
  );

  // Digests force-linked in this preview session (before duplicate-check refetch).
  const [linkedHashKeys, setLinkedHashKeys] = useState<Set<string>>(() => new Set());
  const [linkRowIndex, setLinkRowIndex] = useState<number | null>(null);
  const [linkMessage, setLinkMessage] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);

  // Prefer import_hash / import_hashes when present; fall back to
  // date|amount|description (type omitted so expense→transfer still matches).
  const existingKeys = useMemo(() => {
    const keys = new Set<string>(linkedHashKeys);
    for (const tx of existingTransactions.data ?? []) {
      if (tx.import_hash) keys.add(`hash:${tx.import_hash}`);
      for (const row of tx.import_hashes ?? []) {
        keys.add(`hash:${row.import_hash}`);
      }
      keys.add(transactionDedupeKey(tx.date, tx.amount, tx.description));
    }
    return keys;
  }, [existingTransactions.data, linkedHashKeys]);

  const { candidates, skipped } = useMemo(() => {
    if (step !== "preview") return { candidates: [] as TransactionInput[], skipped: [] as SkippedRow[] };

    const dateIdx = headers.indexOf(mapping.date);
    const amountIdx = headers.indexOf(mapping.amount);
    const descIdx = headers.indexOf(mapping.description);
    const merchantIdx = mapping.merchant ? headers.indexOf(mapping.merchant) : -1;
    const notesIdx = mapping.notes ? headers.indexOf(mapping.notes) : -1;
    const categoryIdx = mapping.category ? headers.indexOf(mapping.category) : -1;

    const rows: TransactionInput[] = [];
    const skippedRows: SkippedRow[] = [];

    dataRows.forEach((cells, index) => {
      const rowNumber = index + 2; // header is row 1
      const rawDate = cells[dateIdx] ?? "";
      const rawAmount = cells[amountIdx] ?? "";
      const rawDescription = (cells[descIdx] ?? "").trim();
      const rawMerchant = merchantIdx >= 0 ? (cells[merchantIdx] ?? "").trim() : "";
      const rawNotes = notesIdx >= 0 ? (cells[notesIdx] ?? "").trim() : "";
      const rawCategory = categoryIdx >= 0 ? (cells[categoryIdx] ?? "").trim() : "";

      // Bank-profile row filter first (e.g. T-Bank's "Статус" = FAILED):
      // a declined payment parses perfectly well as a date + amount, and
      // nothing downstream could tell it apart from a real expense.
      const rejectedStatus = rowFilterRejection(activePreset, headers, cells);
      if (rejectedStatus !== null) {
        skippedRows.push({ row: rowNumber, reason: t("transactions.import.errorRowFiltered", { value: rejectedStatus || "—" }) });
        return;
      }

      const parsedDate = parseDateTimeWithFormat(rawDate, dateFormat);
      if (!parsedDate) {
        skippedRows.push({ row: rowNumber, reason: t("transactions.import.errorBadDate", { value: rawDate || "—" }) });
        return;
      }
      const amount = parseAmount(rawAmount, amountFormat);
      if (amount === null || amount === 0) {
        skippedRows.push({ row: rowNumber, reason: t("transactions.import.errorBadAmount", { value: rawAmount || "—" }) });
        return;
      }
      // Alfa-Bank (and similar) store absolute amounts; debit/credit is a
      // separate column — applyAmountSign folds that into the sign the
      // rest of the wizard already understands.
      const signed = applyAmountSign(activePreset, headers, cells, amount);
      if (signed === null) {
        skippedRows.push({
          row: rowNumber,
          reason: t("transactions.import.errorBadDirection", {
            value: amountSignColumnValue(activePreset, headers, cells) || "—",
          }),
        });
        return;
      }
      const description = rawDescription || rawMerchant;
      if (!description) {
        skippedRows.push({ row: rowNumber, reason: t("transactions.import.errorNoDescription") });
        return;
      }

      const type = resolveType(signed);
      const categoryId = rawCategory ? categoryLookup[type].get(rawCategory.toLowerCase()) ?? null : null;

      rows.push({
        account_id: Number(accountId),
        category_id: categoryId,
        transfer_account_id: null,
        type,
        amount: Math.abs(signed).toFixed(2),
        description,
        merchant: rawMerchant || null,
        notes: rawNotes || null,
        date: parsedDate.date,
        occurred_at: parsedDate.occurred_at,
      });
    });

    return { candidates: rows, skipped: skippedRows };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, headers, dataRows, mapping, dateFormat, amountFormat, categoryLookup, accountId, activePreset, t]);

  // import_hash digests for preview dedupe (async SubtleCrypto).
  const [candidateHashes, setCandidateHashes] = useState<(string | null)[]>([]);

  useEffect(() => {
    if (step !== "preview" || candidates.length === 0) {
      setCandidateHashes([]);
      return;
    }
    let cancelled = false;
    const presetId = activePreset?.id;
    (async () => {
      const digests = await Promise.all(
        candidates.map(async (item) => {
          const occurredAt = item.occurred_at ?? toOccurredAtIso(item.date!, "00:00");
          return computeImportHash({
            accountId: item.account_id,
            date: item.date ?? occurredAt.slice(0, 10),
            occurredAt,
            amount: item.amount,
            description: item.description,
            merchant: item.merchant ?? undefined,
            presetId,
          });
        }),
      );
      if (!cancelled) setCandidateHashes(digests);
    })();
    return () => {
      cancelled = true;
    };
  }, [step, candidates, activePreset?.id]);

  const { valid, isDuplicate, duplicateCount } = useMemo(() => {
    if (step !== "preview") {
      return { valid: [] as TransactionInput[], isDuplicate: [] as boolean[], duplicateCount: 0 };
    }

    const rows: TransactionInput[] = [];
    const dupFlags: boolean[] = [];

    candidates.forEach((candidate, index) => {
      const digest = candidateHashes[index] ?? null;
      const key = transactionDedupeKey(candidate.date!, candidate.amount, candidate.description);
      const hashKnown = digest !== null && existingKeys.has(`hash:${digest}`);
      const keyKnown = existingKeys.has(key);
      const withHash = digest ? { ...candidate, import_hash: digest } : candidate;
      // Hash match or same date|amount|description already on the account.
      rows.push(withHash);
      dupFlags.push(hashKnown || keyKnown);
    });

    return {
      valid: rows,
      isDuplicate: dupFlags,
      duplicateCount: dupFlags.filter(Boolean).length,
    };
  }, [step, candidates, candidateHashes, existingKeys]);

  // When the preview list changes, select only non-duplicates by default.
  const validSelectionKey = useMemo(
    () =>
      valid
        .map((row, index) => `${row.date}|${row.amount}|${row.description}|${row.import_hash ?? ""}|${isDuplicate[index] ? "1" : "0"}`)
        .join("\n"),
    [valid, isDuplicate],
  );

  useEffect(() => {
    setSelectedIndexes(
      new Set(valid.flatMap((_, index) => (isDuplicate[index] ? [] : [index]))),
    );
  }, [validSelectionKey, valid, isDuplicate]);

  const linkCandidateParams = useMemo(() => {
    if (linkRowIndex === null) return null;
    const row = valid[linkRowIndex];
    if (!row?.date || !row.amount || !accountId) return null;
    return { account_id: Number(accountId), amount: row.amount, date: row.date };
  }, [linkRowIndex, valid, accountId]);

  const linkCandidates = useImportLinkCandidates(linkCandidateParams);

  async function confirmLinkToTransaction(transactionId: number) {
    if (linkRowIndex === null) return;
    const row = valid[linkRowIndex];
    if (!row?.import_hash || !accountId) return;
    setLinkError(null);
    setLinkMessage(null);
    try {
      await attachImportHashMutation.mutateAsync({
        transactionId,
        account_id: Number(accountId),
        import_hash: row.import_hash,
      });
      setLinkedHashKeys((prev) => new Set(prev).add(`hash:${row.import_hash}`));
      setSelectedIndexes((prev) => {
        const next = new Set(prev);
        next.delete(linkRowIndex);
        return next;
      });
      setLinkMessage(t("transactions.import.linkSuccess"));
      setLinkRowIndex(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setLinkError(t("transactions.import.linkErrorConflict"));
      } else {
        setLinkError(error instanceof ApiError ? error.message : t("transactions.import.linkError"));
      }
    }
  }

  const selectedCount = useMemo(() => {
    let count = 0;
    for (const index of selectedIndexes) {
      if (index >= 0 && index < valid.length) count += 1;
    }
    return count;
  }, [selectedIndexes, valid.length]);

  const allSelected = valid.length > 0 && selectedCount === valid.length;
  const someSelected = selectedCount > 0 && selectedCount < valid.length;

  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected]);

  async function handleFileSelected(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setParseError(null);

    const buffer = await file.arrayBuffer();
    // Invalid-UTF-8 byte sequences almost always mean a Cyrillic bank export
    // in the classic Windows codepage — a far better first guess than
    // staying on UTF-8 and showing every letter as mojibake. The user can
    // still override this from the dropdown on the next screen either way.
    let detectedEncoding: Encoding = "utf-8";
    try {
      new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    } catch {
      detectedEncoding = "windows-1251";
    }

    const rows = parseCsv(new TextDecoder(detectedEncoding).decode(buffer));
    if (rows.length < 2) {
      setParseError(t("transactions.import.errorEmptyFile"));
      return;
    }
    const [headerRow] = rows;
    // Full reset for a fresh file — the header-change effect above skips
    // files whose header row is byte-identical to the previous one, so
    // formats from the last import can't be left over here.
    const defaults = resolveDefaults(headerRow, resolvePreset(headerRow, presetChoice));
    setFileName(file.name);
    setFileBuffer(buffer);
    setEncoding(detectedEncoding);
    setMapping(defaults.mapping);
    setDateFormat(defaults.dateFormat);
    setAmountFormat(defaults.amountFormat);
    setStep("map");
  }

  function applyCsvText(csvText: string, name: string) {
    const buffer = new TextEncoder().encode(csvText).buffer;
    const rows = parseCsv(csvText);
    if (rows.length < 2) {
      setParseError(t("transactions.import.errorEmptyFile"));
      return false;
    }
    const [headerRow] = rows;
    const defaults = resolveDefaults(headerRow, resolvePreset(headerRow, presetChoice));
    setFileName(name);
    setFileBuffer(buffer);
    setEncoding("utf-8");
    setMapping(defaults.mapping);
    setDateFormat(defaults.dateFormat);
    setAmountFormat(defaults.amountFormat);
    setParseError(null);
    setConvertedCsv(csvText);
    setStep("map");
    return true;
  }

  async function handleGpbConvert() {
    if (!accountId || !gpbHtml.trim()) return;
    setParseError(null);
    setGpbConverting(true);
    try {
      const result = await convertGpbHtmlStatement(gpbHtml, htmlToday);
      applyCsvText(result.csv, "gpb-statement.csv");
    } catch (error) {
      setParseError(error instanceof ApiError ? error.message : t("transactions.import.gpbConvertError"));
    } finally {
      setGpbConverting(false);
    }
  }

  async function handleAlfaConvert() {
    if (!accountId || !alfaHtml.trim()) return;
    setParseError(null);
    setAlfaConverting(true);
    try {
      const result = await convertAlfaHtmlStatement(alfaHtml, htmlToday);
      applyCsvText(result.csv, "alfa-statement.csv");
    } catch (error) {
      setParseError(error instanceof ApiError ? error.message : t("transactions.import.alfaConvertError"));
    } finally {
      setAlfaConverting(false);
    }
  }

  function downloadConvertedCsv() {
    if (!convertedCsv) return;
    const blob = new Blob([convertedCsv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName || "gpb-statement.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function startOver() {
    setStep("upload");
    setFileName("");
    setFileBuffer(null);
    setEncoding("utf-8");
    setCreatedCount(null);
    setImportError(null);
    setConvertedCsv(null);
    setGpbHtml("");
    setAlfaHtml("");
    setHtmlToday(todayLocalIso());
    setParseError(null);
    setLinkedHashKeys(new Set());
    setLinkRowIndex(null);
    setLinkMessage(null);
    setLinkError(null);
  }

  function toggleSelectAll(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.checked) setSelectedIndexes(new Set(valid.map((_, index) => index)));
    else setSelectedIndexes(new Set());
  }

  function toggleRowSelected(index: number, checked: boolean) {
    setSelectedIndexes((prev) => {
      const next = new Set(prev);
      if (checked) next.add(index);
      else next.delete(index);
      return next;
    });
  }

  async function handleImport() {
    setImportError(null);
    try {
      const presetId = activePreset?.id;
      const withHashes: TransactionInput[] = [];
      for (let index = 0; index < valid.length; index++) {
        if (!selectedIndexes.has(index)) continue;
        const item = valid[index]!;
        const occurredAt = item.occurred_at ?? toOccurredAtIso(item.date!, "00:00");
        const import_hash =
          item.import_hash ??
          (await computeImportHash({
            accountId: item.account_id,
            date: item.date ?? occurredAt.slice(0, 10),
            occurredAt,
            amount: item.amount,
            description: item.description,
            merchant: item.merchant ?? undefined,
            presetId,
          }));
        // Known fingerprint: backend would skip; don't send unless the user
        // explicitly selected a row that still needs hash backfill (no hash yet).
        if (existingKeys.has(`hash:${import_hash}`)) continue;
        withHashes.push({ ...item, occurred_at: occurredAt, import_hash });
      }
      if (withHashes.length === 0) {
        setCreatedCount(0);
        return;
      }
      const result = await bulkCreate.mutateAsync(withHashes);
      setCreatedCount(result.created);
    } catch (error) {
      setImportError(error instanceof ApiError ? error.message : t("transactions.import.importError"));
    }
  }

  const mappingComplete = Boolean(mapping.date && mapping.amount && mapping.description);

  // Same control on the upload and map steps: picking the bank up front is
  // the "I know what this file is" path, changing it on the map step is the
  // "auto-detect guessed wrong" path.
  const presetSelect = (id: string) => (
    <div>
      <Label htmlFor={id}>{t("transactions.import.presetLabel")}</Label>
      <Select id={id} value={presetChoice} onChange={(event) => setPresetChoice(event.target.value)} className="sm:w-72">
        <option value={PRESET_AUTO}>{t("transactions.import.preset.auto")}</option>
        {BANK_PRESETS.map((preset) => (
          <option key={preset.id} value={preset.id}>
            {preset.label}
          </option>
        ))}
      </Select>
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Link
          to="/transactions"
          aria-label={t("common.back")}
          className="rounded-md p-1.5 text-text-muted hover:bg-surface-2 hover:text-text-primary"
        >
          <ArrowLeft size={18} />
        </Link>
        <h1 className="text-lg font-semibold text-text-primary">{t("transactions.import.title")}</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("transactions.import.accountLabel")}</CardTitle>
        </CardHeader>
        <CardContent>
          <Select value={accountId} onChange={(event) => setAccountId(event.target.value)} className="sm:w-72">
            <option value="" disabled>
              {t("transactions.form.selectAccount")}
            </option>
            {accounts?.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name}
              </option>
            ))}
          </Select>
          <p className="mt-2 text-xs text-text-muted">{t("transactions.import.accountHint")}</p>
        </CardContent>
      </Card>

      {step === "upload" && (
        <Card>
          <CardHeader>
            <CardTitle>{t("transactions.import.uploadTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:gap-3">
              <Button
                type="button"
                variant={uploadSource === "csv" ? "primary" : "ghost"}
                onClick={() => {
                  setUploadSource("csv");
                  setParseError(null);
                }}
                className="sm:flex-1"
              >
                {t("transactions.import.sourceCsv")}
              </Button>
              <Button
                type="button"
                variant={uploadSource === "gpb-html" ? "primary" : "ghost"}
                onClick={() => {
                  setUploadSource("gpb-html");
                  setParseError(null);
                }}
                className="sm:flex-1"
              >
                {t("transactions.import.sourceGpbHtml")}
              </Button>
              <Button
                type="button"
                variant={uploadSource === "alfa-html" ? "primary" : "ghost"}
                onClick={() => {
                  setUploadSource("alfa-html");
                  setParseError(null);
                }}
                className="sm:flex-1"
              >
                {t("transactions.import.sourceAlfaHtml")}
              </Button>
            </div>

            {uploadSource === "csv" ? (
              <>
                <p className="text-sm text-text-secondary">{t("transactions.import.uploadHint")}</p>
                {presetSelect("upload-preset")}
                <p className="text-xs text-text-muted">{t("transactions.import.presetHint")}</p>
                <Button onClick={() => fileInputRef.current?.click()} disabled={!accountId}>
                  <Upload size={16} />
                  {t("transactions.import.chooseFile")}
                </Button>
                <input ref={fileInputRef} type="file" accept=".csv,text/csv" onChange={handleFileSelected} className="hidden" />
              </>
            ) : uploadSource === "gpb-html" ? (
              <>
                <p className="text-sm text-text-secondary">{t("transactions.import.gpbHtmlHint")}</p>
                <div>
                  <Label htmlFor="gpb-today">{t("transactions.import.gpbTodayLabel")}</Label>
                  <Input
                    id="gpb-today"
                    type="date"
                    value={htmlToday}
                    onChange={(event) => setHtmlToday(event.target.value)}
                    className="sm:w-56"
                  />
                  <p className="mt-1 text-xs text-text-muted">{t("transactions.import.gpbTodayHint")}</p>
                </div>
                <div>
                  <Label htmlFor="gpb-html">{t("transactions.import.gpbHtmlLabel")}</Label>
                  <textarea
                    id="gpb-html"
                    value={gpbHtml}
                    onChange={(event) => setGpbHtml(event.target.value)}
                    rows={10}
                    className="w-full rounded-lg border border-border bg-surface-1 px-3 py-2 font-mono text-xs text-text-primary outline-none focus:border-series-1"
                    placeholder={t("transactions.import.gpbHtmlPlaceholder")}
                  />
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    onClick={handleGpbConvert}
                    disabled={!accountId || !gpbHtml.trim() || gpbConverting || !htmlToday}
                  >
                    {gpbConverting ? t("transactions.import.gpbConverting") : t("transactions.import.gpbConvert")}
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-text-secondary">{t("transactions.import.alfaHtmlHint")}</p>
                <div>
                  <Label htmlFor="alfa-today">{t("transactions.import.gpbTodayLabel")}</Label>
                  <Input
                    id="alfa-today"
                    type="date"
                    value={htmlToday}
                    onChange={(event) => setHtmlToday(event.target.value)}
                    className="sm:w-56"
                  />
                  <p className="mt-1 text-xs text-text-muted">{t("transactions.import.gpbTodayHint")}</p>
                </div>
                <div>
                  <Label htmlFor="alfa-html">{t("transactions.import.alfaHtmlLabel")}</Label>
                  <textarea
                    id="alfa-html"
                    value={alfaHtml}
                    onChange={(event) => setAlfaHtml(event.target.value)}
                    rows={10}
                    className="w-full rounded-lg border border-border bg-surface-1 px-3 py-2 font-mono text-xs text-text-primary outline-none focus:border-series-1"
                    placeholder={t("transactions.import.alfaHtmlPlaceholder")}
                  />
                </div>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Button
                    onClick={handleAlfaConvert}
                    disabled={!accountId || !alfaHtml.trim() || alfaConverting || !htmlToday}
                  >
                    {alfaConverting ? t("transactions.import.alfaConverting") : t("transactions.import.alfaConvert")}
                  </Button>
                </div>
              </>
            )}
            {!accountId && <p className="text-xs text-text-muted">{t("transactions.import.pickAccountFirst")}</p>}
            {parseError && <p className="text-sm text-danger">{parseError}</p>}
          </CardContent>
        </Card>
      )}

      {step === "map" && (
        <Card>
          <CardHeader>
            <CardTitle>{t("transactions.import.mapTitle")}</CardTitle>
            <span className="text-xs text-text-muted">{fileName}</span>
          </CardHeader>
          <CardContent className="space-y-3">
            {presetSelect("map-preset")}
            <p className={`text-xs ${activePreset ? "text-success" : "text-text-muted"}`}>
              {activePreset
                ? t("transactions.import.presetDetected", { bank: activePreset.label })
                : t("transactions.import.presetNotDetected")}
            </p>

            <div>
              <Label htmlFor="map-encoding">{t("transactions.import.encodingLabel")}</Label>
              <Select id="map-encoding" value={encoding} onChange={(event) => setEncoding(event.target.value as Encoding)} className="sm:w-56">
                {ENCODINGS.map((enc) => (
                  <option key={enc} value={enc}>
                    {enc.toUpperCase()}
                  </option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-text-muted">{t("transactions.import.encodingHint")}</p>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="map-date">{t("transactions.import.dateColumnLabel")}</Label>
                <Select id="map-date" value={mapping.date} onChange={(event) => setMapping((prev) => ({ ...prev, date: event.target.value }))}>
                  <option value={NONE} disabled>
                    {t("transactions.import.selectColumn")}
                  </option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                {mapping.date && (
                  <p className="mt-1 text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.date) || "—" })}
                  </p>
                )}
              </div>
              <div>
                <Label htmlFor="map-date-format">{t("transactions.import.dateFormatLabel")}</Label>
                <Select id="map-date-format" value={dateFormat} onChange={(event) => setDateFormat(event.target.value as DateFormat)}>
                  {DATE_FORMATS.map((format) => (
                    <option key={format} value={format}>
                      {format}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="map-amount">{t("transactions.import.amountColumnLabel")}</Label>
                <Select id="map-amount" value={mapping.amount} onChange={(event) => setMapping((prev) => ({ ...prev, amount: event.target.value }))}>
                  <option value={NONE} disabled>
                    {t("transactions.import.selectColumn")}
                  </option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                <p className="mt-1 text-xs text-text-muted">{t("transactions.import.amountHint")}</p>
                {mapping.amount && (
                  <p className="text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.amount) || "—" })}
                  </p>
                )}
              </div>
              <div>
                <Label htmlFor="map-amount-format">{t("transactions.import.amountFormatLabel")}</Label>
                <Select id="map-amount-format" value={amountFormat} onChange={(event) => setAmountFormat(event.target.value as AmountFormat)}>
                  {AMOUNT_FORMATS.map((format) => (
                    <option key={format} value={format}>
                      {t(`transactions.import.amountFormat.${format}`)}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label htmlFor="map-description">{t("transactions.import.descriptionColumnLabel")}</Label>
                <Select
                  id="map-description"
                  value={mapping.description}
                  onChange={(event) => setMapping((prev) => ({ ...prev, description: event.target.value }))}
                >
                  <option value={NONE} disabled>
                    {t("transactions.import.selectColumn")}
                  </option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                {mapping.description && (
                  <p className="mt-1 text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.description) || "—" })}
                  </p>
                )}
              </div>
              <div>
                <Label htmlFor="map-merchant">{t("transactions.form.merchantLabel")}</Label>
                <Select id="map-merchant" value={mapping.merchant} onChange={(event) => setMapping((prev) => ({ ...prev, merchant: event.target.value }))}>
                  <option value={NONE}>{t("transactions.import.notMapped")}</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                {mapping.merchant && (
                  <p className="mt-1 text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.merchant) || "—" })}
                  </p>
                )}
              </div>
              <div>
                <Label htmlFor="map-notes">{t("transactions.form.notesLabel")}</Label>
                <Select id="map-notes" value={mapping.notes} onChange={(event) => setMapping((prev) => ({ ...prev, notes: event.target.value }))}>
                  <option value={NONE}>{t("transactions.import.notMapped")}</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                {mapping.notes && (
                  <p className="mt-1 text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.notes) || "—" })}
                  </p>
                )}
              </div>
              <div>
                <Label htmlFor="map-category">{t("transactions.form.categoryLabel")}</Label>
                <Select id="map-category" value={mapping.category} onChange={(event) => setMapping((prev) => ({ ...prev, category: event.target.value }))}>
                  <option value={NONE}>{t("transactions.import.notMapped")}</option>
                  {headers.map((header) => (
                    <option key={header} value={header}>
                      {header}
                    </option>
                  ))}
                </Select>
                <p className="mt-1 text-xs text-text-muted">{t("transactions.import.categoryHint")}</p>
                {mapping.category && (
                  <p className="text-xs text-text-muted">
                    {t("transactions.import.sampleValueLabel", { value: sampleValue(mapping.category) || "—" })}
                  </p>
                )}
              </div>
            </div>

            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
              <Button variant="ghost" onClick={startOver}>
                {t("transactions.import.startOver")}
              </Button>
              {convertedCsv && (
                <Button variant="secondary" type="button" onClick={downloadConvertedCsv}>
                  {t("transactions.import.downloadCsv")}
                </Button>
              )}
              <Button disabled={!mappingComplete} onClick={() => setStep("preview")}>
                {t("transactions.import.previewButton")}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === "preview" && (
        <Card>
          <CardHeader>
            <CardTitle>{t("transactions.import.previewTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {createdCount !== null ? (
              <div className="space-y-3">
                <p className="text-sm text-success">{t("transactions.import.importSuccess", { count: createdCount })}</p>
                <Button onClick={() => navigate("/transactions")}>{t("transactions.import.goToTransactions")}</Button>
              </div>
            ) : (
              <>
                <p className="text-sm text-text-secondary">
                  {t("transactions.import.summary", { valid: valid.length, skipped: skipped.length })}
                </p>

                {existingTransactions.isFetching && (
                  <p className="text-xs text-text-muted">{t("transactions.import.duplicateCheckLoading")}</p>
                )}

                {existingTransactions.isError && (
                  <p className="text-sm text-danger">{t("transactions.import.duplicateCheckFailed")}</p>
                )}

                {duplicateCount > 0 && (
                  <p className="rounded-lg border border-border bg-surface-2 p-3 text-xs text-text-muted">
                    {t("transactions.import.duplicatesFound", { count: duplicateCount })}
                  </p>
                )}

                {linkMessage && (
                  <p className="rounded-lg border border-border bg-surface-2 p-3 text-xs text-success">{linkMessage}</p>
                )}

                {valid.length > 0 && (
                  <div className="max-h-[min(24rem,55vh)] overflow-auto rounded-lg border border-border">
                    <table className="w-full text-left text-sm">
                      <thead className="sticky top-0 bg-surface-2 text-xs text-text-muted">
                        <tr>
                          <th className="w-10 px-3 py-2">
                            <input
                              ref={selectAllRef}
                              type="checkbox"
                              checked={allSelected}
                              onChange={toggleSelectAll}
                              aria-label={t("transactions.import.selectAll")}
                              className="h-3.5 w-3.5 accent-text-primary"
                            />
                          </th>
                          <th className="px-3 py-2 font-medium">{t("transactions.form.dateLabel")}</th>
                          <th className="px-3 py-2 font-medium">{t("transactions.form.descriptionLabel")}</th>
                          <th className="hidden px-3 py-2 font-medium sm:table-cell">{t("transactions.form.categoryLabel")}</th>
                          <th className="px-3 py-2 text-right font-medium">{t("transactions.form.amountLabel")}</th>
                          <th className="px-2 py-2 font-medium" />
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gridline">
                        {valid.map((item, index) => (
                          <tr key={index} className={selectedIndexes.has(index) ? undefined : "opacity-50"}>
                            <td className="px-3 py-1.5">
                              <input
                                type="checkbox"
                                checked={selectedIndexes.has(index)}
                                onChange={(event) => toggleRowSelected(index, event.target.checked)}
                                aria-label={t("transactions.import.selectRow", { row: index + 1 })}
                                className="h-3.5 w-3.5 accent-text-primary"
                              />
                            </td>
                            <td className="whitespace-nowrap px-3 py-1.5 text-text-secondary">{item.date}</td>
                            <td className="px-3 py-1.5 text-text-primary">
                              <span className="block">{item.description}</span>
                              <button
                                type="button"
                                className="mt-0.5 text-xs text-text-muted underline-offset-2 hover:underline sm:hidden"
                                disabled={!item.import_hash || attachImportHashMutation.isPending}
                                onClick={() => {
                                  setLinkError(null);
                                  setLinkRowIndex(index);
                                }}
                              >
                                {t("transactions.import.linkButton")}
                              </button>
                            </td>
                            <td className="hidden whitespace-nowrap px-3 py-1.5 text-text-secondary sm:table-cell">
                              {categories?.find((c) => c.id === item.category_id)
                                ? translateCategoryName(categories.find((c) => c.id === item.category_id)!.name)
                                : "—"}
                            </td>
                            <td
                              className={`whitespace-nowrap px-3 py-1.5 text-right tabular-nums ${
                                item.type === "expense" ? "text-text-primary" : "text-success"
                              }`}
                            >
                              {item.type === "expense" ? "-" : "+"}
                              {formatCurrency(item.amount)}
                            </td>
                            <td className="hidden whitespace-nowrap px-2 py-1.5 text-right sm:table-cell">
                              <Button
                                type="button"
                                variant="ghost"
                                className="h-auto px-2 py-1 text-xs"
                                disabled={!item.import_hash || attachImportHashMutation.isPending}
                                onClick={() => {
                                  setLinkError(null);
                                  setLinkRowIndex(index);
                                }}
                              >
                                {t("transactions.import.linkButton")}
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {skipped.length > 0 && (
                  <div className="max-h-40 overflow-y-auto rounded-lg border border-border bg-surface-2 p-3 text-xs text-text-muted">
                    {skipped.map((row) => (
                      <p key={row.row}>{t("transactions.import.skippedRow", { row: row.row, reason: row.reason })}</p>
                    ))}
                  </div>
                )}

                {importError && <p className="text-sm text-danger">{importError}</p>}

                <div className="flex justify-end gap-2 pt-2">
                  <Button variant="ghost" onClick={() => setStep("map")}>
                    {t("common.back")}
                  </Button>
                  {/* isFetching, not isLoading: a background refetch of the
                      duplicate check still serves stale data, and importing
                      against that would wave duplicates straight through. */}
                  <Button
                    disabled={selectedCount === 0 || bulkCreate.isPending || existingTransactions.isFetching}
                    onClick={() => void handleImport()}
                  >
                    {bulkCreate.isPending
                      ? t("common.saving")
                      : t("transactions.import.importButton", { count: selectedCount })}
                  </Button>
                </div>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog
        open={linkRowIndex !== null}
        onClose={() => {
          if (attachImportHashMutation.isPending) return;
          setLinkRowIndex(null);
          setLinkError(null);
        }}
        title={t("transactions.import.linkTitle")}
      >
        <div className="space-y-3 text-sm">
          <p className="text-xs text-text-muted">{t("transactions.import.linkHint")}</p>
          {linkRowIndex !== null && valid[linkRowIndex] && (
            <p className="rounded-md border border-border bg-surface-2 p-2 text-xs text-text-secondary">
              {valid[linkRowIndex]!.date} · {valid[linkRowIndex]!.description} ·{" "}
              {formatCurrency(valid[linkRowIndex]!.amount)}
            </p>
          )}
          {linkCandidates.isFetching && (
            <p className="text-xs text-text-muted">{t("transactions.import.linkLoading")}</p>
          )}
          {linkCandidates.isError && (
            <p className="text-sm text-danger">{t("transactions.import.linkFailed")}</p>
          )}
          {linkCandidates.isSuccess && linkCandidates.data.length === 0 && (
            <p className="text-xs text-text-muted">{t("transactions.import.linkEmpty")}</p>
          )}
          {linkCandidates.data && linkCandidates.data.length > 0 && (
            <ul className="max-h-64 space-y-2 overflow-y-auto">
              {linkCandidates.data.map((tx) => (
                <li key={tx.id} className="flex items-start justify-between gap-2 rounded-md border border-border p-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-text-primary">{tx.description}</p>
                    <p className="truncate text-xs text-text-muted">
                      {t(`transactions.${tx.type}` as TranslationKey)} · {tx.account.name}
                      {tx.transfer_account ? ` → ${tx.transfer_account.name}` : ""} ·{" "}
                      {formatTransactionDate(tx.date, true)} · {formatCurrency(tx.amount, tx.account.currency)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={attachImportHashMutation.isPending}
                    onClick={() => void confirmLinkToTransaction(tx.id)}
                  >
                    {t("transactions.import.linkConfirm")}
                  </Button>
                </li>
              ))}
            </ul>
          )}
          {linkError && <p className="text-sm text-danger">{linkError}</p>}
        </div>
      </Dialog>
    </div>
  );
}
