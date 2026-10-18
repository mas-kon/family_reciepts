from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Kind
from app.db.models import Category
from app.db.session import rowcount
from app.i18n import LANGUAGES, t

OTHER = "other"
INCOME_OTHER = "income.other"

# system categories by stable key; their names come from the message catalogs (`cat.<key>`)
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "groceries": [
        "vegetables",
        "meat_fish",
        "dairy_eggs",
        "bakery",
        "pantry",
        "sweets",
        "drinks",
        "alcohol",
        "ready_meals",
        "frozen",
    ],
    "household": ["chemicals", "home_goods", "repairs"],
    "hygiene": [],
    "health": ["pharmacy", "doctors"],
    "kids": [],
    "pets": [],
    "transport": ["fuel", "taxi_transit", "car_service", "parking"],
    "cafe": [],
    "housing": ["rent", "electricity", "water", "heating", "internet_phone"],
    "clothes": [],
    "electronics": [],
    "entertainment": [],
    "subscriptions": [],
    "gifts": [],
    "education": [],
    "travel": [],
    "taxes": [],
    "deposit": [],
    OTHER: [],
}

INCOME_CATEGORIES = [
    "income.salary",
    "income.side_job",
    "income.gifts_help",
    "income.refunds",
    "income.interest_cashback",
    INCOME_OTHER,
]


def _system_keys() -> list[tuple[str, str | None, str]]:
    """(key, parent key, kind) of every system category."""
    rows: list[tuple[str, str | None, str]] = []
    for parent, children in DEFAULT_CATEGORIES.items():
        rows.append((parent, None, Kind.EXPENSE))
        rows += [(f"{parent}.{c}", parent, Kind.EXPENSE) for c in children]
    rows += [(k, None, Kind.INCOME) for k in INCOME_CATEGORIES]
    return rows


def category_name(key: str, lang: str | None = None) -> str:
    return t(f"cat.{key}", lang=lang)


async def fail_interrupted(session: AsyncSession) -> int:
    """At startup nothing is being recognised yet: records still 'pending' were cut off by a
    restart. Mark them failed, so they show the reason and can be re-read in the web app."""
    from sqlalchemy import update

    from app.db.models import Receipt

    res = await session.execute(
        update(Receipt)
        .where(Receipt.status == "pending")
        .values(status="failed", review_reason=t("record.interrupted"))
    )
    await session.commit()
    return rowcount(res)


async def seed_categories(session: AsyncSession) -> None:
    """Create the default categories in the family's language, once; adopt existing categories
    that have no key yet (a database made before keys existed) by their name in any language."""
    rows = _system_keys()
    existing = list(await session.scalars(select(Category)))
    by_key = {c.key: c for c in existing if c.key}
    for key, parent_key, kind in rows:
        if key in by_key:
            continue
        if parent_key and parent_key not in by_key:
            continue
        parent_id = by_key[parent_key].id if parent_key else None
        names = {category_name(key, lang) for lang in LANGUAGES}
        for c in existing:
            if c.key is None and c.parent_id == parent_id and c.kind == kind and c.name in names:
                c.key = key
                by_key[key] = c
                break
    await session.flush()
    for kind in (Kind.INCOME, Kind.EXPENSE):
        if any(c.kind == kind for c in existing):
            continue  # set up already, maybe pruned by hand
        for i, (key, parent_key, _) in enumerate(r for r in rows if r[2] == kind):
            if key in by_key:
                continue
            cat = Category(
                key=key,
                name=category_name(key),
                kind=kind,
                parent_id=by_key[parent_key].id if parent_key else None,
                sort_order=(100 + i) if kind == Kind.INCOME else _order(key),
            )
            session.add(cat)
            await session.flush()
            by_key[key] = cat
    await session.commit()


def _order(key: str) -> int:
    parent, _, child = key.partition(".")
    siblings = list(DEFAULT_CATEGORIES)
    return siblings.index(parent) if not child else DEFAULT_CATEGORIES[parent].index(child)


async def translate_categories(session: AsyncSession, lang: str) -> None:
    """After a language switch: system categories take their names in the new language. A category
    the family renamed by hand (its name is none of the catalog names) keeps its name."""
    siblings = list(await session.scalars(select(Category)))
    for c in siblings:
        if not c.key:
            continue
        known = {category_name(c.key, code) for code in LANGUAGES}
        new = category_name(c.key, lang)
        if c.name not in known or c.name == new:
            continue
        if any(o.id != c.id and o.parent_id == c.parent_id and o.name == new for o in siblings):
            continue
        c.name = new
    await session.commit()


