"""Parse Alfa-Bank operation-history HTML into an Alfa CSV the import wizard
already understands (preset ``alfabank``).

The online UI emits hashed CSS class names that change; we key off stable
``data-test-id`` / ``data-date`` attributes instead.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Iterator


CSV_HEADERS = [
    "operationDate",
    "transactionDate",
    "accountName",
    "accountNumber",
    "cardName",
    "cardNumber",
    "merchant",
    "amount",
    "currency",
    "status",
    "category",
    "mcc",
    "type",
    "comment",
    "bonusValue",
    "bonusTitle",
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

# «сегодня» / «вчера, 5 ноября» / «среда, 4 ноября»
_DATE_NAMED_RE = re.compile(
    r"(?:^|,\s*)(\d{1,2})\s+(" + "|".join(_MONTHS_RU.keys()) + r")\b",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"^([+\u2212\-–—]?)\s*([\d\s\u00a0\u202f\u205f]+(?:[.,]\d{1,2})?)\s*₽?$",
)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


@dataclass
class AlfaOperation:
    operation_date: str  # DD.MM.YYYY
    amount: str  # absolute, dot-decimal
    direction: str  # Списание | Пополнение
    merchant: str
    category: str
    comment: str
    bonus_value: str


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
        if tag.lower() not in {"br", "img", "hr", "meta", "link", "input", "svg", "path", "rect", "defs", "clippath", "g", "use"}:
            self._stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"br", "img", "hr", "meta", "link", "input", "svg", "path", "rect", "defs", "clippath", "g", "use"}:
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


def _all_text(node: _Node) -> str:
    parts: list[str] = []
    for n in _walk(node):
        if n.text is not None:
            parts.append(n.text)
    return "".join(parts).strip()


def _test_id(node: _Node) -> str:
    return node.attrs.get("data-test-id", "") or node.attrs.get("data-testid", "")


def _find_descendants(node: _Node, *, test_id: str | None = None, tag: str | None = None) -> list[_Node]:
    out: list[_Node] = []
    for n in _walk(node):
        if n.tag is None:
            continue
        if test_id is not None and _test_id(n) != test_id:
            continue
        if tag is not None and n.tag != tag:
            continue
        if test_id is None and tag is None:
            continue
        out.append(n)
    return out


def parse_section_date(label: str, today: date) -> date | None:
    """Resolve a day-group label relative to `today` when data-date is absent."""
    text = " ".join(label.split()).strip()
    if not text:
        return None
    lowered = text.casefold()
    if lowered.startswith("сегодня"):
        return today
    if lowered.startswith("вчера"):
        return today - timedelta(days=1)

    match = _DATE_NAMED_RE.search(text)
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


def parse_data_date(raw: str) -> date | None:
    """Parse ``data-date="2026-11-06T12:12:58.658+0300"`` calendar day."""
    text = (raw or "").strip()
    match = _ISO_DATE_RE.match(text)
    if not match:
        # Some browsers normalize offset with a colon (+03:00).
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _format_date(day: date) -> str:
    return f"{day.day:02d}.{day.month:02d}.{day.year}"


def _parse_signed_amount(raw: str) -> tuple[str, str] | None:
    """Return (absolute_dot_decimal, Списание|Пополнение) or None."""
    cleaned = (
        raw.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u205f", " ")
        .replace("₽", "")
        .strip()
    )
    # Collapse internal spaces used as thousand separators.
    match = _AMOUNT_RE.match(cleaned) or _AMOUNT_RE.match(re.sub(r"\s+", "", cleaned))
    if not match:
        # Status block may be "-3 800,00 ₽" split across nodes; try without spaces.
        compact = re.sub(r"\s+", "", cleaned)
        match = _AMOUNT_RE.match(compact)
        if not match:
            return None

    sign_token, number = match.group(1), match.group(2)
    number = (
        number.replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace("\u205f", "")
    )
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    try:
        value = abs(float(number))
    except ValueError:
        return None

    negative = sign_token in {"-", "–", "—", "\u2212"} or any(
        c in raw for c in "-–—\u2212"
    )
    # Leading '+' or credit styling without minus → income.
    if sign_token == "+":
        negative = False
    direction = "Списание" if negative else "Пополнение"
    amount = f"{value:.2f}"
    return amount, direction


def _extract_bonus(cell: _Node) -> str:
    nodes = _find_descendants(cell, test_id="bonus")
    if not nodes:
        return ""
    text = _all_text(nodes[0])
    # Drop the trailing currency unit from bonus-rur sibling text.
    text = text.replace("₽", "").replace("\u00a0", " ").replace("\u202f", " ").strip()
    text = re.sub(r"\s+", "", text)
    return text


def _extract_operation(cell: _Node, day: date) -> AlfaOperation | None:
    titles = _find_descendants(cell, test_id="title-text_content")
    merchant = _all_text(titles[0]).strip() if titles else ""
    if not merchant:
        return None

    cats = _find_descendants(cell, test_id="transaction-category-name")
    category = _all_text(cats[0]).strip() if cats else ""

    status_nodes = _find_descendants(cell, test_id="transaction-status")
    if not status_nodes:
        return None
    amount_raw = _all_text(status_nodes[0])
    parsed = _parse_signed_amount(amount_raw)
    if parsed is None:
        return None
    amount, direction = parsed

    footers = _find_descendants(cell, test_id="operation-cell-footer")
    comment = _all_text(footers[0]).strip() if footers else ""

    return AlfaOperation(
        operation_date=_format_date(day),
        amount=amount,
        direction=direction,
        merchant=merchant,
        category=category,
        comment=comment,
        bonus_value=_extract_bonus(cell),
    )


def _is_date_label(text: str) -> bool:
    cleaned = " ".join(text.split()).strip()
    if not cleaned or len(cleaned) > 60:
        return False
    lowered = cleaned.casefold()
    if lowered.startswith("сегодня") or lowered.startswith("вчера"):
        return True
    return _DATE_NAMED_RE.search(cleaned) is not None


def _has_ancestor_data_date(node: _Node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.attrs.get("data-date"):
            return True
        ancestor = ancestor.parent
    return False


def parse_alfa_html(html: str, *, today: date) -> list[AlfaOperation]:
    """Walk Alfa history HTML and return operations in document order."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()

    current_day: date | None = None
    operations: list[AlfaOperation] = []

    for node in _walk(builder.root):
        # Day header: prefer machine-readable data-date on the group marker.
        if node.tag is not None and node.attrs.get("data-date"):
            resolved = parse_data_date(node.attrs["data-date"])
            if resolved is not None:
                current_day = resolved

        # Fallback when the paste has no data-date (relative / named labels).
        elif node.tag == "span" and not _has_ancestor_data_date(node):
            label = _all_text(node)
            if label and _is_date_label(label):
                resolved = parse_section_date(label, today)
                if resolved is not None:
                    current_day = resolved

        if node.tag is None:
            continue
        if _test_id(node) != "operation-cell":
            continue
        if current_day is None:
            continue
        op = _extract_operation(node, current_day)
        if op is not None:
            operations.append(op)

    return operations


def operations_to_csv(operations: list[AlfaOperation]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(CSV_HEADERS)
    for op in operations:
        writer.writerow(
            [
                op.operation_date,
                op.operation_date,
                "",
                "",
                "",
                "",
                op.merchant,
                op.amount,
                "RUR",
                "Выполнен",
                op.category,
                "",
                op.direction,
                op.comment,
                op.bonus_value,
                "",
            ]
        )
    return buf.getvalue()


def convert_alfa_html_to_csv(html: str, *, today: date) -> tuple[str, int]:
    ops = parse_alfa_html(html, today=today)
    return operations_to_csv(ops), len(ops)
