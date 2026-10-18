"""Aggregations over items. All amounts are in EUR.

Spending counts only records of kind "expense": incomes are summed separately and transfers
inside the family are counted nowhere (they are only moved money)."""

from datetime import date, datetime, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.clock import now_local
from app.constants import Kind
from app.db.models import (
    Budget,
    BudgetAlert,
    Category,
    Item,
    ProductAlias,
    Receipt,
    User,
)

EUR = Item.total
# product key: canonical product if grouped (app.products), otherwise the line's own name
PRODUCT_KEY = func.coalesce(ProductAlias.product, Item.name_normalized)


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """'2026-03' -> [2026-03-01, 2026-04-01)."""
    y, m = map(int, month.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), m % 12 + 1, 1)
    return start, end


def prev_month(d: date) -> str:
    first = d.replace(day=1) - timedelta(days=1)
    return f"{first:%Y-%m}"


def _filtered(
    q: Select,
    date_from: datetime | None,
    date_to: datetime | None,
    user_id: int | None = None,
    kind: Kind = Kind.EXPENSE,
) -> Select:
    conds = [Receipt.status != "failed", Receipt.kind == kind]
    if date_from:
        conds.append(Receipt.purchased_at >= date_from)
    if date_to:
        conds.append(Receipt.purchased_at < date_to)
    if user_id:
        conds.append(Receipt.user_id == user_id)
    return q.where(and_(*conds))


async def summary(
    session: AsyncSession,
    date_from: datetime | None,
    date_to: datetime | None,
    user_id: int | None = None,
    top: int = 15,
) -> dict:
    Parent = aliased(Category)
    top_cat_id = func.coalesce(Category.parent_id, Category.id)

    total = await session.scalar(
        _filtered(
            select(func.coalesce(func.sum(EUR), 0)).select_from(Item).join(Receipt, Item.receipt_id == Receipt.id),
            date_from,
            date_to,
            user_id,
        )
    )

    receipts_count = await session.scalar(
        _filtered(
            select(func.count(func.distinct(Receipt.id)))
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id),
            date_from,
            date_to,
            user_id,
        )
    )

    by_top = await session.execute(
        _filtered(
            select(
                top_cat_id.label("id"),
                func.coalesce(Parent.name, Category.name).label("name"),
                func.sum(EUR).label("amount"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(Category, Item.category_id == Category.id)
            .outerjoin(Parent, Category.parent_id == Parent.id),
            date_from,
            date_to,
            user_id,
        )
        .group_by(top_cat_id, func.coalesce(Parent.name, Category.name))
        .order_by(func.sum(EUR).desc())
    )

    by_leaf = await session.execute(
        _filtered(
            select(
                Category.id,
                Category.name,
                Parent.name.label("parent"),
                func.sum(EUR).label("amount"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(Category, Item.category_id == Category.id)
            .outerjoin(Parent, Category.parent_id == Parent.id),
            date_from,
            date_to,
            user_id,
        )
        .group_by(Category.id, Category.name, Parent.name)
        .order_by(func.sum(EUR).desc())
    )

    by_user = await session.execute(
        _filtered(
            select(User.id, User.name, func.sum(EUR).label("amount"))
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(User, Receipt.user_id == User.id),
            date_from,
            date_to,
            user_id,
        )
        .group_by(User.id, User.name)
        .order_by(func.sum(EUR).desc())
    )

    by_store = await session.execute(
        _filtered(
            select(
                func.coalesce(Receipt.store, "—").label("store"),
                func.sum(EUR).label("amount"),
                func.count(func.distinct(Receipt.id)).label("receipts"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id),
            date_from,
            date_to,
            user_id,
        )
        .where(Receipt.source == "photo")
        .group_by(func.coalesce(Receipt.store, "—"))
        .order_by(func.sum(EUR).desc())
        .limit(top)
    )

    top_items = await session.execute(
        _filtered(
            select(
                PRODUCT_KEY.label("name_normalized"),
                func.coalesce(func.max(ProductAlias.product), func.max(Item.name_ru)).label("name_ru"),
                func.sum(EUR).label("amount"),
                func.count(Item.id).label("count"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(ProductAlias, ProductAlias.name_normalized == Item.name_normalized),
            date_from,
            date_to,
            user_id,
        )
        .where(Item.total > 0)
        .group_by(PRODUCT_KEY)
        .order_by(func.sum(EUR).desc())
        .limit(top)
    )

    income = await income_summary(session, date_from, date_to, user_id)
    transfers = await session.scalar(
        _filtered(select(func.coalesce(func.sum(Receipt.total), 0)), date_from, date_to, user_id, kind=Kind.TRANSFER)
    )

    def rows(res):
        return [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r._mapping.items()} for r in res]

    return {
        "total": round(total or 0, 2),
        "receipts": receipts_count or 0,
        "by_category": rows(by_top),
        "by_subcategory": rows(by_leaf),
        "by_user": rows(by_user),
        "by_store": rows(by_store),
        "top_items": rows(top_items),
        "income": income,
        "transfers_total": round(transfers or 0, 2),
    }


async def income_summary(
    session: AsyncSession, date_from: datetime | None, date_to: datetime | None, user_id: int | None = None
) -> dict:
    by_cat = await session.execute(
        _filtered(
            select(
                func.coalesce(Category.name, "Без категории").label("name"),
                func.sum(EUR).label("amount"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(Category, Item.category_id == Category.id),
            date_from,
            date_to,
            user_id,
            kind=Kind.INCOME,
        )
        .group_by(func.coalesce(Category.name, "Без категории"))
        .order_by(func.sum(EUR).desc())
    )
    cats = [{"name": r.name, "amount": round(r.amount, 2)} for r in by_cat]
    return {"total": round(sum(c["amount"] for c in cats), 2), "by_category": cats}


async def monthly(session: AsyncSession, months: int = 12, user_id: int | None = None) -> list[dict]:
    """Totals per month per top-level category for the last N months."""
    Parent = aliased(Category)
    today = now_local().date()
    y, m = today.year, today.month - (months - 1)
    while m <= 0:
        m += 12
        y -= 1
    start = datetime(y, m, 1)
    # strftime is SQLite-specific; for PostgreSQL use func.to_char(..., "YYYY-MM")
    month_expr = func.strftime("%Y-%m", Receipt.purchased_at)
    res = await session.execute(
        _filtered(
            select(
                month_expr.label("month"),
                func.coalesce(Parent.name, Category.name, "Без категории").label("category"),
                func.sum(EUR).label("amount"),
            )
            .select_from(Item)
            .join(Receipt, Item.receipt_id == Receipt.id)
            .outerjoin(Category, Item.category_id == Category.id)
            .outerjoin(Parent, Category.parent_id == Parent.id),
            start,
            None,
            user_id,
        ).group_by(month_expr, func.coalesce(Parent.name, Category.name, "Без категории"))
    )
    incomes = await session.execute(
        _filtered(
            select(month_expr.label("month"), func.sum(Receipt.total).label("amount")),
            start,
            None,
            user_id,
            kind=Kind.INCOME,
        ).group_by(month_expr)
    )
    by_month: dict[str, dict] = {}
    for r in incomes:
        by_month[r.month] = {"month": r.month, "total": 0.0, "income": round(r.amount or 0, 2), "categories": {}}
    for r in res:
        row = by_month.setdefault(r.month, {"month": r.month, "total": 0.0, "income": 0.0, "categories": {}})
        row["categories"][r.category] = round(r.amount, 2)
        row["total"] = round(row["total"] + r.amount, 2)
    # fill gaps so charts have a continuous axis
    out = []
    cy, cm = y, m
    for _ in range(months):
        key = f"{cy:04d}-{cm:02d}"
        out.append(by_month.get(key, {"month": key, "total": 0.0, "income": 0.0, "categories": {}}))
        cm += 1
        if cm > 12:
            cm, cy = 1, cy + 1
    return out


# ---------- budgets ----------


async def category_ids_with_children(session: AsyncSession, category_id: int) -> list[int]:
    children = await session.scalars(select(Category.id).where(Category.parent_id == category_id))
    return [category_id, *children]


async def spent_in_category(session: AsyncSession, category_id: int, month: str) -> float:
    start, end = month_bounds(month)
    ids = await category_ids_with_children(session, category_id)
    q = _filtered(
        select(func.coalesce(func.sum(EUR), 0)).select_from(Item).join(Receipt, Item.receipt_id == Receipt.id),
        start,
        end,
    ).where(Item.category_id.in_(ids))
    return round(await session.scalar(q) or 0, 2)


async def budgets_status(session: AsyncSession, month: str) -> list[dict]:
    budgets = list(await session.scalars(select(Budget)))
    out = []
    for b in budgets:
        spent = await spent_in_category(session, b.category_id, month)
        out.append(
            {
                "id": b.id,
                "category_id": b.category_id,
                "category": b.category.name,
                "amount": b.amount,
                "spent": spent,
                "percent": round(spent / b.amount * 100, 1) if b.amount else 0,
            }
        )
    return out


async def new_budget_alerts(session: AsyncSession, receipt: Receipt) -> list[str]:
    """Messages for budgets that just crossed 80% / 100% this month because of this receipt."""
    if not receipt.purchased_at:
        return []
    month = f"{receipt.purchased_at:%Y-%m}"
    if month != f"{now_local():%Y-%m}":
        return []
    cat_ids = {i.category_id for i in receipt.items if i.category_id}
    if not cat_ids:
        return []
    parents = await session.scalars(select(Category.parent_id).where(Category.id.in_(cat_ids)))
    touched = cat_ids | {p for p in parents if p}
    budgets = list(await session.scalars(select(Budget).where(Budget.category_id.in_(touched))))
    messages = []
    for b in budgets:
        spent = await spent_in_category(session, b.category_id, month)
        pct = spent / b.amount * 100 if b.amount else 0
        level = 100 if pct >= 100 else 80 if pct >= 80 else None
        if level is None:
            continue
        sent = set(
            await session.scalars(
                select(BudgetAlert.level).where(BudgetAlert.budget_id == b.id, BudgetAlert.month == month)
            )
        )
        if level in sent:
            continue
        # mark lower levels as sent too, so 80% never arrives after 100%
        # ON CONFLICT: when two receipts cross the line at once, only one of them reports it
        claimed = True
        for lvl in (80, 100):
            if lvl <= level and lvl not in sent:
                res = await session.execute(
                    sqlite_insert(BudgetAlert).values(budget_id=b.id, month=month, level=lvl).on_conflict_do_nothing()
                )
                if lvl == level and not res.rowcount:
                    claimed = False
        if not claimed:
            continue
        if level == 100:
            messages.append(f"🔴 Бюджет «{b.category.name}» превышен: {spent:.2f} € из {b.amount:.2f} €")
        else:
            messages.append(f"🟡 Бюджет «{b.category.name}»: потрачено {pct:.0f}% ({spent:.2f} € из {b.amount:.2f} €)")
    await session.commit()
    return messages
