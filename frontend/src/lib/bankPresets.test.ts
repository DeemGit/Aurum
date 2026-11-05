import { describe, expect, it } from "vitest";
import { applyPresetMapping, detectPreset, findPreset, normalizeHeader, rowFilterRejection, type ImportMapping } from "@/lib/bankPresets";
import { parseAmount, parseCsv, parseDateWithFormat } from "@/lib/csv";

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

describe("normalizeHeader", () => {
  it("folds case, whitespace, BOM and the Latin i", () => {
    expect(normalizeHeader("﻿  Дата  i   час ")).toBe("дата і час");
  });
});

describe("detectPreset", () => {
  it("recognises T-Bank, monobank and PrivatBank header rows", () => {
    expect(detectPreset(parseCsv(TBANK_CSV)[0])?.id).toBe("tbank");
    expect(detectPreset(parseCsv(MONOBANK_CSV)[0])?.id).toBe("monobank");
    expect(detectPreset(parseCsv(PRIVAT_CSV)[0])?.id).toBe("privatbank");
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
