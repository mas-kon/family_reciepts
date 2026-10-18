from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.api.receipts import end_of, start_of
from app.api.schemas import Ok
from app.config import get_settings
from app.db.models import Item, ProductAlias, Receipt
from app.db.session import get_session, icontains
from app.i18n import t
from app.products import with_alias
from app.scheduler import send_monthly_report
from app.stats import PRODUCT_KEY, monthly, summary

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(current_viewer)])


class CategoryAmount(BaseModel):
    id: int | None
    name: str | None
    amount: float


class SubcategoryAmount(CategoryAmount):
    parent: str | None


class StoreAmount(BaseModel):
    store: str
    amount: float
    receipts: int


class TopItem(BaseModel):
    name_normalized: str
    name_ru: str | None
    amount: float
    count: int


class NamedAmount(BaseModel):
    name: str
    amount: float


class IncomeSummary(BaseModel):
    total: float
    by_category: list[NamedAmount]


class SummaryOut(BaseModel):
    total: float
    receipts: int
    by_category: list[CategoryAmount]
    by_subcategory: list[SubcategoryAmount]
    by_user: list[CategoryAmount]
    by_store: list[StoreAmount]
    top_items: list[TopItem]
    income: IncomeSummary
    # money moved inside the family: neither spent nor earned
    transfers_total: float


class MonthRow(BaseModel):
    month: str
    total: float
    income: float
    categories: dict[str, float]


class ProductOut(BaseModel):
    key: str
    name: str | None
    name_original: str
    variants: int
    count: int
    min_price: float | None
    max_price: float | None
    last_date: datetime | None


class PricePoint(BaseModel):
    receipt_id: int
    purchased_at: datetime | None
    store: str | None
    name_original: str
    qty: float
    unit_price_eur: float | None


@router.get("/stats/summary", response_model=SummaryOut)
async def stats_summary(
    session: AsyncSession = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: int | None = None,
):
    return await summary(session, start_of(date_from), end_of(date_to), user_id)


@router.get("/stats/monthly", response_model=list[MonthRow])
async def stats_monthly(
    session: AsyncSession = Depends(get_session),
    months: int = Query(12, ge=1, le=60),
    user_id: int | None = None,
    # a chosen period replaces "the last N months"
    date_from: date | None = None,
    date_to: date | None = None,
):
    return await monthly(session, months, user_id, date_from, date_to)


@router.get("/products", response_model=list[ProductOut])
async def products(
    session: AsyncSession = Depends(get_session),
    q: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
):
    """Products for price tracking. Lines grouped under one product (Цены → Объединить or the
    automatic grouping) count as one product; `key` identifies it in the other endpoints."""
    query = (
        with_alias(
            select(
                PRODUCT_KEY.label("key"),
                func.coalesce(func.max(ProductAlias.product), func.max(Item.name_ru)).label("name"),
                func.max(Item.name_original).label("name_original"),
                func.count(func.distinct(Item.name_normalized)).label("variants"),
                func.count(Item.id).label("count"),
                func.min(Item.unit_price).label("min_price"),
                func.max(Item.unit_price).label("max_price"),
                func.max(Receipt.purchased_at).label("last_date"),
            ).join(Receipt, Item.receipt_id == Receipt.id)
        )
        .where(Item.total > 0, Receipt.source.in_(("photo", "email")))
        .group_by(PRODUCT_KEY)
        .order_by(func.count(Item.id).desc(), func.max(Receipt.purchased_at).desc())
        .limit(limit)
    )
    if q:
        query = query.where(icontains(Item.name_original, q) | icontains(Item.name_ru, q) | icontains(PRODUCT_KEY, q))
    rows = await session.execute(query)
    return [
        {
            **r._mapping,
            "min_price": round(r.min_price, 2) if r.min_price is not None else None,
            "max_price": round(r.max_price, 2) if r.max_price is not None else None,
        }
        for r in rows
    ]


@router.get("/products/prices", response_model=list[PricePoint])
async def product_prices(key: str, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        with_alias(
            select(
                Receipt.id.label("receipt_id"),
                Receipt.purchased_at,
                Receipt.store,
                Item.name_original,
                Item.qty,
                Item.unit_price.label("unit_price_eur"),
            ).join(Receipt, Item.receipt_id == Receipt.id)
        )
        .where(PRODUCT_KEY == key, Item.total > 0)
        .order_by(Receipt.purchased_at)
    )
    return [{**r._mapping, "unit_price_eur": round(r.unit_price_eur, 2) if r.unit_price_eur else None} for r in rows]


@router.post("/reports/send", response_model=Ok)
async def send_report(request: Request, month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    bot = getattr(request.app.state, "bot", None)
    if not bot or not get_settings().notify_chat_id:
        raise HTTPException(400, t("api.no_bot"))
    await send_monthly_report(bot, month)
    return Ok()
