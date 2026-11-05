# Multicurrency, Refund, Cashback — Aurum Design

Целевая модель учёта нескольких счетов в разных валютах, переводов с курсом
и комиссией, точного времени операций, refund, кешбека, дедупа импорта и
сопоставления переводных пар.

**Стек:** FastAPI, SQLAlchemy 2.0, PostgreSQL, Alembic, React, TypeScript,
Docker Compose, локализации `ru` / `en`.

**Миграция данных:** semantic backfill / переписывание истории **не
делается**. Только Alembic `ADD COLUMN` / `CREATE TABLE` с безопасными
default. Существующие суммы не меняются. Для `occurred_at` — одноразовый
`UPDATE` из `date` (заполнение времени, не смена финансовой семантики).

---

## 1. Счета

- `Account.currency` задаётся **только при создании**.
- `PATCH` смены `currency` → HTTP 400.
- Тип `cash` — без тарифов кешбека.

Баланс по-прежнему derived (не колонка).

## 2. Время операции

| Поле | Роль |
|------|------|
| `occurred_at` | `TIMESTAMPTZ` — точное время |
| `date` | календарный день для фильтров / месячных отчётов |

Write: `occurred_at` или только `date` → `occurred_at = date 00:00:00+00`.
При записи `date` синхронизируется из `occurred_at` (UTC date).

## 3. Перевод (одна строка)

Поля: `amount` (списание), `transfer_amount` (зачисление), `exchange_rate`
(optional), `fee_amount` (default 0).

Баланс:

- source `-= amount + fee_amount`
- dest `+= transfer_amount`
- same-currency без `transfer_amount` → `transfer_amount = amount`
- `fee_amount` не входит в income/expense/category totals

Кешбек на transfer запрещён: `cashback_category_id` / `cashback_amount` = NULL.

## 4. Refund (`type=refund`)

- Обязателен `refund_of_transaction_id` → expense.
- Тот же `account_id`; `amount > 0`; сумма refund ≤ остаток покупки.
- Баланс: `+amount` в месяце/дате refund.
- Траты месяца **покупки**: spent -= linked refunds (по `date` исходной expense).
- Не income и не expense в dashboard type-totals.
- **Кешбек:** `cashback_amount` вручную, может быть **отрицательным**
  (банк списывает ранее начисленный кешбек). Optional `cashback_category_id`.

## 5. Matching переводных пар

Кандидат: другой счёт, противоположный тип (expense↔income), та же сумма,
близкий `occurred_at` (окно ±2 дня, сортировка по `|Δt|`).

Merge → одна transfer-строка; две старые удаляются.

При merge / смене type→transfer: кешбек **обнуляется**.

`import_hash` после merge: hash source (expense).

## 6. Кешбек

Отдельно от `categories`:

- `cashback_categories` — банковские градации
- `account_cashback_rates` — `(account_id, year, month, cashback_category_id, percent)`
- Expense: optional `cashback_category_id` → expected = amount × %
- Actual: income с `is_cashback=true` + `cashback_amount` на refund (со знаком)
- Счета `cash`: тарифы запрещены

## 7. `import_hash`

- `String(64)` SHA-256 hex, nullable (ручные → NULL)
- Unique `(account_id, import_hash)` WHERE NOT NULL
- Bulk: skip duplicates → `skipped_duplicates` в ответе
- Канон: account_id + date/time + amount + description (+ merchant) + preset id

## 8. Фильтр по счёту

API уже: `GET /transactions?account_id=`. UI: select + deep-link со страницы счетов.

## 9. Отчёты и агрегаты

| Поверхность | Поведение |
|-------------|-----------|
| Account balance | per-currency; transfer dual amount + fee |
| Dashboard spent | expenses − refunds attributed to that month’s expenses |
| Cash flow | exclude transfer; exclude refund-as-type; expense − attributed refunds; +refunds_received в месяце refund в net |
| Category reports | то же attribution для spent |
| Cross-currency totals | breakdown по валютам, без тихого sum |
| Cashback report | expected vs actual |

## 10. Последовательность реализации

1. Дизайн-док (этот файл)
2. Схема + ORM
3. API core (accounts, transactions, balances, reports)
4. import_hash dedupe
5. Transfer matching
6. Кешбек CRUD + отчёт
7. Frontend datetime / filter / i18n + тесты

## 11. Ограничения MVP

- Нет таблицы рыночных `exchange_rates`
- После merge hash второй ноги не хранится
- Нет авто-кнопки «начислить кешбек по %»
