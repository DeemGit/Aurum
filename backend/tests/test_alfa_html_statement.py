"""Alfa-Bank operation-history HTML → Alfa CSV (alfabank preset)."""
from datetime import date
from pathlib import Path

from app.services.alfa_html_statement import (
    convert_alfa_html_to_csv,
    parse_alfa_html,
    parse_data_date,
    parse_section_date,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "alfa_history_snippet.html").read_text(encoding="utf-8")
TODAY = date(2026, 11, 6)


def test_parse_data_date_iso_with_offset():
    assert parse_data_date("2026-11-06T12:12:58.658+0300") == date(2026, 11, 6)
    assert parse_data_date("2026-11-05T08:24:49.325+03:00") == date(2026, 11, 5)


def test_parse_section_date_relative_and_named():
    assert parse_section_date("сегодня", TODAY) == date(2026, 11, 6)
    assert parse_section_date("вчера, 5 ноября", TODAY) == date(2026, 11, 5)
    assert parse_section_date("среда, 4 ноября", TODAY) == date(2026, 11, 4)
    assert parse_section_date("4 ноября", date(2026, 1, 10)) == date(2025, 11, 4)


def test_parse_alfa_html_skips_banner_keeps_bonus_and_footer():
    ops = parse_alfa_html(FIXTURE, today=TODAY)
    assert [op.merchant for op in ops] == [
        "Вячеслав Т.",
        "6е",
        "CP  BUNGLYBOO",
        "FOBIYA.BAUMANKA",
        "Пополнение из другого банка через СБП",
    ]
    assert all("расходы" not in op.merchant.casefold() for op in ops)

    assert ops[0].operation_date == "06.11.2026"
    assert ops[0].amount == "3800.00"
    assert ops[0].direction == "Списание"
    assert ops[0].category == "Переводы · СБП · Сбербанк"
    assert ops[0].comment == "Перевод денежных средств"

    assert ops[2].operation_date == "05.11.2026"
    assert ops[2].amount == "7458.75"
    assert ops[2].direction == "Пополнение"
    assert ops[2].category == "Пополнения"

    assert ops[3].operation_date == "04.11.2026"
    assert ops[3].amount == "5950.00"
    assert ops[3].direction == "Списание"
    assert ops[3].bonus_value == "+767"
    assert ops[3].category == "Активный отдых"

    assert ops[4].direction == "Пополнение"
    assert ops[4].comment == "Запрос денежных средств Me2Me"


def test_convert_csv_has_alfabank_detectable_headers():
    csv_text, count = convert_alfa_html_to_csv(FIXTURE, today=TODAY)
    assert count == 5
    header = csv_text.splitlines()[0]
    assert "operationDate" in header
    assert "transactionDate" in header
    assert "amount" in header
    assert "type" in header
    assert "merchant" in header
    assert "Списание" in csv_text
    assert "Пополнение" in csv_text
    assert "Выполнен" in csv_text
    assert "Все ваши расходы" not in csv_text


def test_fallback_labels_without_data_date():
    html = """
    <section data-test-id="operations-history">
      <div>
        <span>сегодня</span>
        <button data-test-id="operation-cell">
          <div data-test-id="title-text_content">Cafe</div>
          <span data-test-id="transaction-category-name">Кафе</span>
          <div data-test-id="transaction-status">-<span>100<span>,00 ₽</span></span></div>
        </button>
      </div>
      <div>
        <span>вчера</span>
        <button data-test-id="operation-cell">
          <div data-test-id="title-text_content">Refund</div>
          <span data-test-id="transaction-category-name">Пополнения</span>
          <div data-test-id="transaction-status">+<span>50<span>,00 ₽</span></span></div>
        </button>
      </div>
    </section>
    """
    ops = parse_alfa_html(html, today=TODAY)
    assert len(ops) == 2
    assert ops[0].operation_date == "06.11.2026"
    assert ops[0].direction == "Списание"
    assert ops[1].operation_date == "05.11.2026"
    assert ops[1].direction == "Пополнение"
