"""GPB operation-history HTML → tbank-compatible CSV."""
from datetime import date
from pathlib import Path

from app.services.gpb_html_statement import (
    convert_gpb_html_to_csv,
    parse_gpb_html,
    parse_section_date,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "gpb_history_snippet.html").read_text(encoding="utf-8")
TODAY = date(2026, 11, 6)


def test_parse_section_date_relative_and_named():
    assert parse_section_date("Сегодня", TODAY) == date(2026, 11, 6)
    assert parse_section_date("Вчера", TODAY) == date(2026, 11, 5)
    assert parse_section_date("4 ноября, ср", TODAY) == date(2026, 11, 4)
    # Past New Year: label later in calendar than today → previous year
    assert parse_section_date("4 ноября, ср", date(2026, 1, 10)) == date(2025, 11, 4)


def test_parse_gpb_html_skips_ads_keeps_pending_and_cashback():
    ops = parse_gpb_html(FIXTURE, today=TODAY)
    assert [op.description for op in ops] == [
        "Merchant One",
        "SHOP ALPHA",
        "Pending Cafe",
        "Points conversion",
        "Marketplace",
    ]
    assert ops[0].occurred_at == "06.11.2026 02:17:00"
    assert ops[0].amount == "-2100,00"
    assert ops[0].category == "Перевод•Т-Банк"

    assert ops[1].occurred_at == "05.11.2026 16:44:00"
    assert ops[1].amount == "-487,90"

    assert ops[2].occurred_at == "05.11.2026 12:34:00"
    assert ops[2].amount == "-2698,00"

    assert ops[3].occurred_at == "04.11.2026 22:28:00"
    assert ops[3].amount == "21024,00"

    assert ops[4].bonuses == "108,00"
    assert ops[4].amount == "-2709,00"


def test_convert_csv_has_tbank_detectable_headers():
    csv_text, count = convert_gpb_html_to_csv(FIXTURE, today=TODAY)
    assert count == 5
    header = csv_text.splitlines()[0]
    assert "Дата операции" in header
    assert "Сумма в валюте счёта" in header
    assert "Описание" in header
    assert "Статус" in header
    assert '"Ок"' in csv_text
    assert "Promo ad" not in csv_text
