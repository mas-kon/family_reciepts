"""Questions in plain language ("сколько ушло на кафе за лето?").

The model never touches the database: it can only call the read-only functions below, which
reuse the same queries as the statistics pages.
"""

import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_local
from app.config import get_settings
from app.constants import Kind
from app.db.models import Category, Item, Receipt, User
from app.db.session import icontains
from app.family import find_user
from app.i18n import t
from app.llm.client import LLMClient, LLMError, get_llm
from app.llm.prompt import ASK_SYSTEM, localize
from app.products import with_alias
from app.receipts.text import leaf_categories
from app.stats import PRODUCT_KEY, monthly, summary

log = logging.getLogger(__name__)

MAX_STEPS = 6
MAX_TOOL_CHARS = 12000


def _date(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.combine(date.fromisoformat(v[:10]), datetime.min.time())
    except ValueError:
        return None


def _end(v: str | None) -> datetime | None:
    d = _date(v)
    return d + timedelta(days=1) if d else None


PERIOD = {
    "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD, включительно"},
    "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD, включительно"},
    "person": {"type": "string", "description": "Имя члена семьи, если вопрос про одного человека"},
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": "Итоги за период: расходы всего, по категориям, подкатегориям, людям, "
            "магазинам, самые затратные товары; income: доходы по категориям; transfers_total: "
            "переводы внутри семьи (не расход и не доход).",
            "parameters": {"type": "object", "properties": PERIOD},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly",
            "description": "Расходы (total) и доходы (income) по месяцам, расходы по категориям "
            "верхнего уровня, за последние N месяцев.",
            "parameters": {
                "type": "object",
                "properties": {
                    "months": {"type": "integer", "description": "Сколько месяцев, 1–36"},
                    "person": PERIOD["person"],
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_purchases",
            "description": "Поиск покупок по названию товара, магазину или описанию. Возвращает "
            "сумму, количество и последние покупки с датой, магазином и ценой. Ищи по корню слова "
            "на {lang} и по-болгарски (названия в чеках).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Слово для поиска"},
                    "category": {"type": "string", "description": "Категория или подкатегория"},
                    "kind": {
                        "type": "string",
                        "enum": ["expense", "income"],
                        "description": "expense: покупки (по умолчанию), income: доходы",
                    },
                    **PERIOD,
                },
            },
        },
    },
]


async def _person_id(session: AsyncSession, person: str | None) -> int | None:
    if not person:
        return None
    u = await find_user(session, person)
    return u.id if u else -1  # -1: unknown person -> empty result


async def _category_ids(session: AsyncSession, name: str | None) -> list[int] | None:
    if not name:
        return None
    # the model may pass the full path "Продукты / Сладости и снеки"
    key = name.split("/")[-1].strip().lower()
    cats = list(await session.scalars(select(Category)))
    hit = [c for c in cats if c.name.lower() == key] or [c for c in cats if key in c.name.lower()]
    ids = {c.id for c in hit} | {c.id for c in cats if c.parent_id in {h.id for h in hit}}
    return list(ids) or [-1]


async def tool_get_summary(session, date_from=None, date_to=None, person=None):
    s = await summary(session, _date(date_from), _end(date_to), await _person_id(session, person), top=10)
    return s


async def tool_get_monthly(session, months=12, person=None):
    months = max(1, min(int(months or 12), 36))
    return await monthly(session, months, await _person_id(session, person))


async def tool_search_purchases(
    session, query=None, category=None, date_from=None, date_to=None, person=None, kind=None
):
    conds = [Receipt.status != "failed", Receipt.kind == ("income" if kind == Kind.INCOME else "expense")]
    if query:
        conds.append(
            or_(
                icontains(Item.name_original, query),
                icontains(Item.name_ru, query),
                icontains(PRODUCT_KEY, query),
                icontains(Receipt.store, query),
                icontains(Receipt.note, query),
            )
        )
    if (cids := await _category_ids(session, category)) is not None:
        conds.append(Item.category_id.in_(cids))
    if d := _date(date_from):
        conds.append(Receipt.purchased_at >= d)
    if d := _end(date_to):
        conds.append(Receipt.purchased_at < d)
    if (pid := await _person_id(session, person)) is not None:
        conds.append(Receipt.user_id == pid)

    base = with_alias(select(Item).join(Receipt, Item.receipt_id == Receipt.id)).where(*conds)
    agg = (
        await session.execute(
            with_alias(
                select(func.coalesce(func.sum(Item.total), 0), func.count(Item.id))
                .select_from(Item)
                .join(Receipt, Item.receipt_id == Receipt.id)
            ).where(*conds)
        )
    ).one()
    rows = await session.execute(
        base.with_only_columns(
            Receipt.purchased_at,
            Receipt.store,
            User.name,
            Item.name_ru,
            Item.name_original,
            Item.qty,
            Item.unit_price,
            Item.total,
        )
        .outerjoin(User, Receipt.user_id == User.id)
        .order_by(Receipt.purchased_at.desc())
        .limit(30)
    )
    return {
        "total": round(agg[0], 2),
        "count": agg[1],
        "latest": [
            {
                "date": f"{r.purchased_at:%Y-%m-%d}" if r.purchased_at else None,
                "store": r.store,
                "who": r.name,
                "item": r.name_ru or r.name_original,
                "qty": r.qty,
                "unit_price": r.unit_price,
                "total": r.total,
            }
            for r in rows
        ],
    }


HANDLERS = {
    "get_summary": tool_get_summary,
    "get_monthly": tool_get_monthly,
    "search_purchases": tool_search_purchases,
}


def _tools() -> list[dict]:
    """The tool descriptions with the family's language filled in."""
    return json.loads(json.dumps(TOOLS).replace("{lang}", t("prompt.lang")))


async def answer(
    session: AsyncSession, question: str, history: list[dict] | None = None, llm: LLMClient | None = None
) -> dict:
    llm = llm or get_llm()
    cats = ", ".join(
        leaf_categories(list(await session.scalars(select(Category).where(Category.kind == Kind.EXPENSE))))
    )
    family = ", ".join(u.name for u in await session.scalars(select(User))) or t("voice.nobody")
    system = (
        localize(ASK_SYSTEM).replace("{today}", f"{now_local():%Y-%m-%d}")
        .replace("{categories}", cats)
        .replace("{family}", family)
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for h in (history or [])[-6:]:
        if h.get("role") in {"user", "assistant"} and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])[:4000]})
    messages.append({"role": "user", "content": question[:2000]})

    used: list[str] = []
    model = None
    for _ in range(MAX_STEPS):
        msg, model = await llm.chat_tools(messages, _tools(), get_settings().ask_models)
        calls = msg.tool_calls or []
        if not calls:
            return {"answer": (msg.content or "").strip() or t("ask.no_answer"), "model": model, "tools": used}
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in calls
                ],
            }
        )
        for c in calls:
            used.append(c.function.name)
            handler = HANDLERS.get(c.function.name)
            try:
                args = json.loads(c.function.arguments or "{}")
                result = await handler(session, **args) if handler else {"error": "unknown function"}
            except Exception as e:  # bad arguments from the model
                log.warning("tool %s failed: %s", c.function.name, e)
                result = {"error": str(e)[:300]}
            content = json.dumps(result, ensure_ascii=False, default=str)[:MAX_TOOL_CHARS]
            messages.append({"role": "tool", "tool_call_id": c.id, "content": content})
    raise LLMError(t("ask.too_many_steps"))
