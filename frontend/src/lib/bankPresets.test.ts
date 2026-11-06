import { describe, expect, it } from "vitest";
import {
  applyAmountSign,
  applyPresetMapping,
  detectPreset,
  findPreset,
  normalizeHeader,
  rowFilterRejection,
  type ImportMapping,
} from "@/lib/bankPresets";
import {
  localOffsetSuffix,
  parseAmount,
  parseCsv,
  parseDateTimeWithFormat,
  parseDateWithFormat,
  toOccurredAtIso,
} from "@/lib/csv";

const EMPTY: ImportMapping = { date: "", amount: "", description: "", merchant: "", notes: "", category: "" };

// Header rows as the banks actually emit them (see the per-preset comments in
// lib/bankPresets.ts for where each export comes from).
const TBANK_CSV = [
  '"Имя счёта";"Номер карты";"Дата операции";"Сумма операции";"Валюта операции";"Сумма в валюте счёта";"Валюта счёта";"Статус";"Категория по-умолчанию";"Ваша категория";"MCC";"Описание";"Сообщение";"Округление";"Сумма операции с округлением";"Бонусы (включая кэшбэк)";"Учёт в аналитике"',
  // Status «Ок» is what current T-Bank exports use (Cyrillic); Latin OK still accepted.
  '"Black";"*8305";"24.10.2018 17:04:25";"-882,04";"RUB";"-882,04";"RUB";"Ок";"Переводы";"Переводы";"";"Пополнение счета Тинькофф Брокер";"комментарий";"0,00";"-882,04";"0,00";"Да"',
  '"Black";"*8305";"25.10.2018 09:12:00";"-1500,00";"RUB";"-1500,00";"RUB";"FAILED";"Супермаркеты";"Супермаркеты";"5411";"Пятёрочка";"";"";"-1500,00";"0,00";"Да"',
].join("\n");

const MONOBANK_CSV = [
  // Latin "i" in "Дата i час" is deliberate — that's what the real file has.
  '"Дата i час операції","Деталі операції",MCC,"Сума в валюті картки (UAH)","Сума в валюті операції",Валюта,Курс,"Сума комісій (UAH)","Сума кешбеку (UAH)","Залишок після операції"',
  '"01.03.2024 12:30:45","Сільпо",5411,-250.50,-250.50,UAH,—,—,2.50,10000.00',
].join("\n");

const PRIVAT_CSV = [
  "Дата;Час;Категорія;Картка;Опис операції;Сума в валюті картки;Валюта картки;Сума в валюті транзакції;Валюта транзакції;Залишок на кінець періоду;Валюта залишку",
  "05.02.2024;14:05;Продукти;5168****1234;АТБ;-320,00;UAH;-320,00;UAH;1500,00;UAH",
].join("\n");

// Alfa-Bank web statement CSV — absolute amounts, direction in `type`.
// Account/card numbers redacted; shape matches real exports.
const ALFA_CSV = [
  "operationDate,transactionDate,accountName,accountNumber,cardName,cardNumber,merchant,amount,currency,status,category,mcc,type,comment,bonusValue,bonusTitle",
  '04.11.2026,05.11.2026,"Текущий счёт",************4026,"Карта Alfa Only",220015******1112,"MOSKVA\\SHOP",5950,RUR,Выполнен,"Активный отдых",7996,Списание,,+767,Рубли',
  '04.11.2026,04.11.2026,"Текущий счёт",************4026,,,"Перевод по СБП",6000,RUR,,Переводы,,Пополнение,,,',
].join("\n");

describe("normalizeHeader", () => {
  it("folds case, whitespace, BOM and the Latin i", () => {
    expect(normalizeHeader("﻿  Дата  i   час ")).toBe("дата і час");
  });
});

describe("detectPreset", () => {
  it("recognises T-Bank, monobank, PrivatBank and Alfa-Bank header rows", () => {
    expect(detectPreset(parseCsv(TBANK_CSV)[0])?.id).toBe("tbank");
    expect(detectPreset(parseCsv(MONOBANK_CSV)[0])?.id).toBe("monobank");
    expect(detectPreset(parseCsv(PRIVAT_CSV)[0])?.id).toBe("privatbank");
    expect(detectPreset(parseCsv(ALFA_CSV)[0])?.id).toBe("alfabank");
  });

  it("returns null for a generic export", () => {
    expect(detectPreset(["Date", "Amount", "Description"])).toBeNull();
  });
});

describe("applyPresetMapping", () => {
  it("maps T-Bank onto the account-currency amount, user category and message", () => {
    const headers = parseCsv(TBANK_CSV)[0];
    const mapping = applyPresetMapping(findPreset("tbank")!, headers, EMPTY);
    expect(mapping).toMatchObject({
      date: "Дата операции",
      amount: "Сумма в валюте счёта",
      description: "Описание",
      category: "Ваша категория",
      notes: "Сообщение",
    });
  });

  it("matches monobank's currency-suffixed amount header by prefix", () => {
    const headers = parseCsv(MONOBANK_CSV)[0];
    const mapping = applyPresetMapping(findPreset("monobank")!, headers, EMPTY);
    expect(mapping.amount).toBe("Сума в валюті картки (UAH)");
    expect(mapping.date).toBe("Дата i час операції");
  });

  it("leaves fields the preset doesn't cover on the fallback", () => {
    const headers = parseCsv(PRIVAT_CSV)[0];
    const mapping = applyPresetMapping(findPreset("privatbank")!, headers, { ...EMPTY, notes: "Картка" });
    expect(mapping.notes).toBe("Картка");
    expect(mapping.category).toBe("Категорія");
  });

  it("maps Alfa-Bank Latin headers onto operation date, merchant and comment", () => {
    const headers = parseCsv(ALFA_CSV)[0];
    const mapping = applyPresetMapping(findPreset("alfabank")!, headers, EMPTY);
    expect(mapping).toMatchObject({
      date: "operationDate",
      amount: "amount",
      description: "merchant",
      merchant: "merchant",
      category: "category",
      notes: "comment",
    });
  });
});

describe("rowFilterRejection", () => {
  it("keeps Cyrillic Ок and Latin OK, drops FAILED", () => {
    const [headers, okCyrillic, failed] = parseCsv(TBANK_CSV);
    const preset = findPreset("tbank")!;
    expect(rowFilterRejection(preset, headers, okCyrillic)).toBeNull();
    expect(rowFilterRejection(preset, headers, failed)).toBe("FAILED");

    const okLatin = [...okCyrillic];
    const statusIdx = headers.indexOf("Статус");
    okLatin[statusIdx] = "OK";
    expect(rowFilterRejection(preset, headers, okLatin)).toBeNull();
  });

  it("keeps everything when the preset has no filter or the column is absent", () => {
    const [headers, row] = parseCsv(MONOBANK_CSV);
    expect(rowFilterRejection(findPreset("monobank")!, headers, row)).toBeNull();
    expect(rowFilterRejection(findPreset("tbank")!, ["Дата"], ["01.01.2024"])).toBeNull();
    expect(rowFilterRejection(null, headers, row)).toBeNull();
  });

  it("keeps Alfa-Bank Выполнен and empty status", () => {
    const [headers, debit, credit] = parseCsv(ALFA_CSV);
    const preset = findPreset("alfabank")!;
    expect(rowFilterRejection(preset, headers, debit)).toBeNull();
    expect(rowFilterRejection(preset, headers, credit)).toBeNull();
  });
});

describe("applyAmountSign", () => {
  it("negates Alfa-Bank Списание and keeps Пополнение positive", () => {
    const [headers, debit, credit] = parseCsv(ALFA_CSV);
    const preset = findPreset("alfabank")!;
    expect(applyAmountSign(preset, headers, debit, 5950)).toBe(-5950);
    expect(applyAmountSign(preset, headers, credit, 6000)).toBe(6000);
  });

  it("returns null for an unknown Alfa-Bank type", () => {
    const [headers, debit] = parseCsv(ALFA_CSV);
    const preset = findPreset("alfabank")!;
    const bad = [...debit];
    bad[headers.indexOf("type")] = "Hold";
    expect(applyAmountSign(preset, headers, bad, 100)).toBeNull();
  });

  it("leaves the amount alone when the preset has no amountSign", () => {
    const [headers, row] = parseCsv(TBANK_CSV);
    expect(applyAmountSign(findPreset("tbank")!, headers, row, -882.04)).toBe(-882.04);
    expect(applyAmountSign(null, headers, row, 50)).toBe(50);
  });
});

describe("preset formats against real sample rows", () => {
  it("parses T-Bank's timestamped date and comma-decimal amount", () => {
    const [, row] = parseCsv(TBANK_CSV);
    const preset = findPreset("tbank")!;
    // Дата операции = index 2, Сумма в валюте счёта = index 5
    expect(parseDateWithFormat(row[2], preset.dateFormat)).toBe("2018-10-24");
    expect(parseAmount(row[5], preset.amountFormat)).toBe(-882.04);
  });

  it("parses monobank's timestamped date and dot-decimal amount", () => {
    const [, row] = parseCsv(MONOBANK_CSV);
    const preset = findPreset("monobank")!;
    expect(parseDateWithFormat(row[0], preset.dateFormat)).toBe("2024-03-01");
    expect(parseAmount(row[3], preset.amountFormat)).toBe(-250.5);
    // monobank writes empty cells as an em dash — must not parse as 0.
    expect(parseAmount(row[6], preset.amountFormat)).toBeNull();
  });

  it("parses PrivatBank's plain date and comma amount", () => {
    const [, row] = parseCsv(PRIVAT_CSV);
    const preset = findPreset("privatbank")!;
    expect(parseDateWithFormat(row[0], preset.dateFormat)).toBe("2024-02-05");
    expect(parseAmount(row[5], preset.amountFormat)).toBe(-320);
  });

  it("parses Alfa-Bank's plain date and absolute dot-decimal amount", () => {
    const [, row] = parseCsv(ALFA_CSV);
    const preset = findPreset("alfabank")!;
    expect(parseDateWithFormat(row[0], preset.dateFormat)).toBe("2026-11-04");
    expect(parseAmount(row[7], preset.amountFormat)).toBe(5950);
  });
});

describe("parseDateWithFormat with a time suffix", () => {
  it("accepts an optional trailing time in every format", () => {
    expect(parseDateWithFormat("2024-01-05T09:30", "YYYY-MM-DD")).toBe("2024-01-05");
    expect(parseDateWithFormat("05/01/2024 09:30:15", "DD/MM/YYYY")).toBe("2024-01-05");
    expect(parseDateWithFormat("01/05/2024 9:30", "MM/DD/YYYY")).toBe("2024-01-05");
    expect(parseDateWithFormat("05-01-2024 09:30", "DD-MM-YYYY")).toBe("2024-01-05");
  });

  it("still rejects trailing garbage that isn't a time", () => {
    expect(parseDateWithFormat("05.01.2024 abc", "DD.MM.YYYY")).toBeNull();
    expect(parseDateWithFormat("05.01.2024 09", "DD.MM.YYYY")).toBeNull();
  });
});

describe("parseDateTimeWithFormat local offset", () => {
  it("tags bank wall-clock with the browser offset, not hard-coded +00:00", () => {
    const parsed = parseDateTimeWithFormat("05.11.2026 16:14:01", "DD.MM.YYYY");
    expect(parsed).not.toBeNull();
    expect(parsed!.date).toBe("2026-11-05");
    expect(parsed!.occurred_at).toMatch(/^2026-11-05T16:14:01[+-]\d{2}:\d{2}$/);
    // Must match browser offset for that wall clock — never a hard-coded UTC tag.
    expect(parsed!.occurred_at).toBe(
      `2026-11-05T16:14:01${localOffsetSuffix(new Date(2026, 10, 5, 16, 14, 1))}`,
    );
  });

  it("uses midnight local when the CSV row has no time", () => {
    const parsed = parseDateTimeWithFormat("05.11.2026", "DD.MM.YYYY");
    expect(parsed!.occurred_at).toBe(
      `2026-11-05T00:00:00${localOffsetSuffix(new Date(2026, 10, 5, 0, 0, 0))}`,
    );
  });

  it("toOccurredAtIso builds the same local-offset form", () => {
    const at = new Date(2026, 10, 5, 16, 14, 0);
    expect(toOccurredAtIso("2026-11-05", "16:14", at)).toBe(
      `2026-11-05T16:14:00${localOffsetSuffix(at)}`,
    );
  });
});
