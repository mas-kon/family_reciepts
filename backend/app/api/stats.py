from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.api.receipts import end_of, start_of
from app.config import get_settings
from app.db.models import Item, Receipt
from app.db.session import get_session, icontains
from app.scheduler import send_monthly_report
from app.stats import monthly, summary

router = APIRouter(prefix="/api", tags=["stats"], dependencies=[Depends(current_viewer)])


@router.get("/stats/summary")
async def stats_summary(
    session: AsyncSession = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
    user_id: int | None = None,
):
    return await summary(session, start_of(date_from), end_of(date_to), user_id)


@router.get("/stats/monthly")
async def stats_monthly(
    session: AsyncSession = Depends(get_session),
    months: int = Query(12, ge=1, le=60),
    user_id: int | None = None,
):
    return await monthly(session, months, user_id)


@router.get("/products")
async def products(
    session: AsyncSession = Depends(get_session),
    q: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Products bought more than once are the interesting ones for price tracking."""
    unit_eur = Item.unit_price
    query = (
        select(
            Item.name_normalized,
            func.max(Item.name_ru).label("name_ru"),
            func.max(Item.name_original).label("name_original"),
            func.count(Item.id).label("count"),
            func.min(unit_eur).label("min_price"),
            func.max(unit_eur).label("max_price"),
            func.max(Receipt.purchased_at).label("last_date"),
        )
        .join(Receipt, Item.receipt_id == Receipt.id)
        .where(Item.total > 0, Receipt.source == "photo")
        .group_by(Item.name_normalized)
        .order_by(func.count(Item.id).desc(), func.max(Receipt.purchased_at).desc())
        .limit(limit)
    )
    if q:
        query = query.where(
            icontains(Item.name_original, q) | icontains(Item.name_ru, q) | icontains(Item.name_normalized, q)
        )
    rows = await session.execute(query)
    return [
        {
            **r._mapping,
            "min_price": round(r.min_price, 2) if r.min_price is not None else None,
            "max_price": round(r.max_price, 2) if r.max_price is not None else None,
        }
        for r in rows
    ]


@router.get("/products/prices")
async def product_prices(name: str, session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(
            Receipt.id.label("receipt_id"),
            Receipt.purchased_at,
            Receipt.store,
            Item.name_original,
            Item.qty,
            Item.unit_price.label("unit_price_eur"),
        )
        .join(Receipt, Item.receipt_id == Receipt.id)
        .where(Item.name_normalized == name, Item.total > 0)
        .order_by(Receipt.purchased_at)
    )
    return [
        {**r._mapping, "unit_price_eur": round(r.unit_price_eur, 2) if r.unit_price_eur else None}
        for r in rows
    ]


@router.post("/reports/send")
async def send_report(request: Request, month: str | None = None):
    bot = getattr(request.app.state, "bot", None)
    if not bot or not get_settings().notify_chat_id:
        raise HTTPException(400, "Бот не запущен или не задан чат для отчётов")
    await send_monthly_report(bot, month)
    return {"ok": True}
