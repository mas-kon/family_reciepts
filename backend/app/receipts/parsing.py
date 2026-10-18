"""Reading what people type: "[Name:] description amount", incomes by keywords, month arithmetic."""

import calendar
import re
from datetime import date

_MANUAL_RE = re.compile(
    r"^(?:(?P<name>.+?)\s+)?(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|евро)?\s*$",
    re.IGNORECASE,
)
_WHO_RE = re.compile(r"^(?P<who>@\w{3,32}|[^\s:@]{2,30}):\s*(?P<rest>.*)$", re.DOTALL)


def parse_manual_text(text: str) -> tuple[str | None, float] | None:
    """'такси 12' -> ('Такси', 12.0); '12,50' -> (None, 12.5). Amounts are in EUR."""
    m = _MANUAL_RE.match(text.strip())
    if not m:
        return None
    name = m["name"].strip().capitalize() if m["name"] else None
    return name, float(m["amount"].replace(",", "."))


_INCOME_RULES = [
    (re.compile(r"зарплат|заплата|аванс|salary|payroll|wage", re.IGNORECASE), "Зарплата"),
    (re.compile(r"возврат|refund|return|възстановен|върнат", re.IGNORECASE), "Возвраты"),
    (re.compile(r"кэшбэк|кешбэк|кешбек|cashback|cash back|процент|лихв|interest", re.IGNORECASE), "Проценты и кэшбэк"),
    (re.compile(r"подработ|фриланс|freelance|гонорар|хонорар", re.IGNORECASE), "Подработка"),
    (re.compile(r"подар|помощ|gift", re.IGNORECASE), "Подарки и помощь"),
]


def income_category_name(name: str) -> str:
    """Income category by keywords; there are few incomes, an LLM call is not worth it."""
    for rx, cat in _INCOME_RULES:
        if rx.search(name or ""):
            return cat
    from app.db.seed import INCOME_OTHER

    return INCOME_OTHER


def split_who(text: str) -> tuple[str | None, str]:
    """'Маша: кино 12' -> ('Маша', 'кино 12'); '@masha: 12' -> ('@masha', '12')."""
    m = _WHO_RE.match((text or "").strip())
    if not m:
        return None, (text or "").strip()
    return m["who"], m["rest"].strip()


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))
