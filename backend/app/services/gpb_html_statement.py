"""Parse Gazprombank (GPB) operation-history HTML into a tbank-compatible CSV.

The bank UI emits styled-components class hashes that change; we key off
stable `data-testid`, `direction`, and `title` attributes instead.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Iterator


CSV_HEADERS = [
    "Дата операции",
    "Сумма операции",
    "Валюта операции",
    "Сумма в валюте счёта",
    "Валюта счёта",
    "Статус",
    "Категория по-умолчанию",
    "Ваша категория",
    "Описание",
    "Сообщение",
    "Бонусы (включая кэшбэк)",
]

_MONTHS_RU = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_DATE_NAMED_RE = re.compile(
    r"^(\d{1,2})\s+(" + "|".join(_MONTHS_RU.keys()) + r")(?:\s*,\s*\S+)?$",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_AMOUNT_RE = re.compile(
    r"^([+\u2212\-–—]?)\s*([\d\s\u00a0\u202f]+(?:[.,]\d{1,2})?)\s*₽?$",
)
_CASHBACK_RE = re.compile(r"([+]?)([\d\s\u00a0\u202f]+(?:[.,]\d{1,2})?)")


@dataclass
class GpbOperation:
    occurred_at: str  # DD.MM.YYYY HH:MM:SS
    amount: str  # comma-decimal with sign
    category: str
    description: str
    bonuses: str


class _Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(
        self,
        *,
        tag: str | None = None,
        attrs: dict[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[_Node] = []
        self.parent: _Node | None = None
        self.text = text

    def append(self, child: _Node) -> None:
        child.parent = self
        self.children.append(child)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node(tag="document")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag=tag.lower(), attrs={k: (v or "") for k, v in attrs})
        self._stack[-1].append(node)
        # Void-ish tags that shouldn't stay open in our tree.
        if tag.lower() not in {"br", "img", "hr", "meta", "link", "input", "svg", "path"}:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"br", "img", "hr", "meta", "link", "input", "svg", "path"}:
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if not data:
            return
        self._stack[-1].append(_Node(text=data))


def _walk(node: _Node) -> Iterator[_Node]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _direct_text(node: _Node) -> str:
    parts: list[str] = []
    for child in node.children:
        if child.text is not None:
            parts.append(child.text)
    return "".join(parts).strip()


def _all_text(node: _Node) -> str:
    parts: list[str] = []
    for n in _walk(node):
        if n.text is not None:
            parts.append(n.text)
    return "".join(parts).strip()


def _testid(node: _Node) -> str:
    return node.attrs.get("data-testid", "")


def _find_descendants(node: _Node, *, testid: str | None = None, tag: str | None = None) -> list[_Node]:
    out: list[_Node] = []
    for n in _walk(node):
        if n.tag is None:
            continue
        if testid is not None and _testid(n) != testid:
            continue
        if tag is not None and n.tag != tag:
            continue
        if testid is None and tag is None:
            continue
        out.append(n)
    return out


def parse_section_date(label: str, today: date) -> date | None:
    """Resolve a day-group label relative to `today`."""
    text = " ".join(label.split()).strip()
    if not text:
        return None
    lowered = text.casefold()
    if lowered == "сегодня":
        return today
    if lowered == "вчера":
        return today - timedelta(days=1)

    match = _DATE_NAMED_RE.match(text)
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS_RU[match.group(2).casefold()]
    year = today.year
    try:
        resolved = date(year, month, day)
    except ValueError:
        return None
    if resolved > today:
        try:
            resolved = date(year - 1, month, day)
        except ValueError:
            return None
    return resolved


def _format_amount(raw: str, direction: str | None) -> str | None:
    cleaned = (
        raw.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("₽", "")
        .strip()
    )
    match = _AMOUNT_RE.match(cleaned) or _AMOUNT_RE.match(cleaned.replace(" ", ""))
    if not match:
        return None

    sign_token, number = match.group(1), match.group(2)
    number = number.replace(" ", "").replace("\u00a0", "").replace("\u202f", "")
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    try:
        value = float(number)
    except ValueError:
        return None

    if direction == "debit":
        negative = True
    elif direction == "credit":
        negative = False
    elif sign_token in {"-", "–", "—", "\u2212"} or any(c in raw for c in "-–—\u2212"):
        negative = True
    else:
        negative = False

    value = -abs(value) if negative else abs(value)
    return f"{value:.2f}".replace(".", ",")


def _format_cashback(raw: str) -> str:
    text = raw.replace("\u00a0", " ").replace("\u202f", " ").strip()
    match = _CASHBACK_RE.search(text)
    if not match:
        return ""
    number = match.group(2).replace(" ", "")
    if "," in number:
        number = number.replace(",", ".")
    try:
        value = abs(float(number))
    except ValueError:
        return ""
    return f"{value:.2f}".replace(".", ",")


def _is_date_label(text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered in {"сегодня", "вчера"}:
        return True
    return _DATE_NAMED_RE.match(cleaned) is not None


def _find_time_near(cell: _Node) -> str | None:
    node: _Node | None = cell
    while node is not None:
        wrappers = _find_descendants(node, testid="swipe-cell-wrapper")
        for wrapper in wrappers:
            for n in _walk(wrapper):
                if n.text is None:
                    continue
                candidate = n.text.strip()
                if _TIME_RE.match(candidate):
                    hh, mm = _TIME_RE.match(candidate).groups()  # type: ignore[union-attr]
                    return f"{int(hh):02d}:{int(mm):02d}"
        # Prefer the nearest ancestor that already contains a wrapper.
        if wrappers:
            break
        node = node.parent
    return None


def _extract_operation(cell: _Node, day: date) -> GpbOperation | None:
    titled = [
        n for n in _find_descendants(cell, tag="p") if n.attrs.get("title")
    ]
    description = ""
    if titled:
        description = titled[0].attrs.get("title") or _all_text(titled[0])
    description = description.strip()
    if not description:
        return None

    amount_nodes = [
        n for n in _find_descendants(cell, tag="p") if n.attrs.get("direction")
    ]
    if not amount_nodes:
        return None
    amount_node = amount_nodes[0]
    direction = amount_node.attrs.get("direction")
    amount = _format_amount(_all_text(amount_node), direction)
    if amount is None:
        return None

    category = ""
    for p in _find_descendants(cell, tag="p"):
        if p is amount_node or p in titled:
            continue
        # Wrapper around the amount / "additional" chrome — not a category.
        if any(c.attrs.get("direction") for c in _find_descendants(p, tag="p")):
            continue
        text = " ".join(_all_text(p).split()).strip()
        if not text or "additional" in text.casefold():
            continue
        if _AMOUNT_RE.match(text):
            continue
        category = text
        break

    bonuses = ""
    cashback_nodes = _find_descendants(cell, testid="cashback")
    if cashback_nodes:
        bonuses = _format_cashback(_all_text(cashback_nodes[0]))

    time_hm = _find_time_near(cell) or "00:00"
    occurred_at = f"{day.day:02d}.{day.month:02d}.{day.year} {time_hm}:00"
    return GpbOperation(
        occurred_at=occurred_at,
        amount=amount,
        category=category,
        description=description,
        bonuses=bonuses,
    )


def parse_gpb_html(html: str, *, today: date) -> list[GpbOperation]:
    """Walk GPB history HTML and return operations in document order."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()

    current_day: date | None = None
    operations: list[GpbOperation] = []

    for node in _walk(builder.root):
        if node.tag == "span":
            label = _direct_text(node) or _all_text(node)
            # Day headers are short labels; avoid picking up nested UI chrome.
            if label and len(label) < 40 and _is_date_label(label):
                resolved = parse_section_date(label, today)
                if resolved is not None:
                    current_day = resolved
                continue

        if node.tag is None:
            continue
        testid = _testid(node)
        if testid == "advertCell":
            continue
        if testid != "historyCell":
            continue
        if current_day is None:
            continue
        op = _extract_operation(node, current_day)
        if op is not None:
            operations.append(op)

    return operations


def operations_to_csv(operations: list[GpbOperation]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    for op in operations:
        writer.writerow(
            [
                op.occurred_at,
                op.amount,
                "RUB",
                op.amount,
                "RUB",
                "Ок",
                op.category,
                op.category,
                op.description,
                "",
                op.bonuses,
            ]
        )
    return buf.getvalue()


def convert_gpb_html_to_csv(html: str, *, today: date) -> tuple[str, int]:
    ops = parse_gpb_html(html, today=today)
    return operations_to_csv(ops), len(ops)
