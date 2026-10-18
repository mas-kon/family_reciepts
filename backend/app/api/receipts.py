import csv
import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import Viewer, current_viewer
from app.db.models import Category, Item, Receipt, User
from app.db.session import get_session, icontains
from app.receipts.money import round2
from app.receipts.service import NO_DESCRIPTION, ReceiptService
from app.receipts.text import normalize_name

router = APIRouter(prefix="/api", tags=["receipts"], dependencies=[Depends(current_viewer)])


# ---------- schemas ----------


class ItemOut(BaseModel):
    id: int
    position: int
    name_original: str
    name_ru: str | None
    name_normalized: str
    qty: float
    unit_price: float | None
    total: float
    category_id: int | None
    warranty_until: date | None


class ReceiptOut(BaseModel):
    id: int
    title: str
    source: str
    store: str | None
    purchased_at: datetime | None
    total: float | None
    status: str
    review_reason: str | None
    user_id: int | None
    user_name: str | None
    items_count: int
    has_image: bool
    note: str | None
    import_id: str | None
    created_at: datetime


class ReceiptDetail(ReceiptOut):
    items: list[ItemOut]
    llm_model: str | None
    qr_raw: str | None
    items_sum: float


class ReceiptPatch(BaseModel):
    store: str | None = None
    purchased_at: datetime | None = None
    total: float | None = None
    status: str | None = None
    note: str | None = None
    user_id: int | None = None


class ItemIn(BaseModel):
    name_original: str
    name_ru: str | None = None
    qty: float = 1
    unit_price: float | None = None
    total: float
    category_id: int | None = None


class ItemPatch(BaseModel):
    name_original: str | None = None
    name_ru: str | None = None
    qty: float | None = None
    unit_price: float | None = None
    total: float | None = None
    category_id: int | None = None
    warranty_until: date | None = None
    # remember the category for this product and apply it to the same product everywhere
    remember: bool = True


class ManualIn(BaseModel):
    # empty name = amount only, booked as "Без описания"
    name: str | None = None
    amount: float
    category_id: int | None = None
    user_id: int | None = None
    purchased_at: datetime | None = None
    store: str | None = None


class ReprocessIn(BaseModel):
    model: str | None = None


# ---------- helpers ----------


def to_out(r: Receipt) -> dict:
    first = r.items[0] if r.items else None
    title = r.store or r.note or (first.name_ru or first.name_original if first else None) or "Чек"
    return dict(
        id=r.id,
        title=title,
        source=r.source,
        store=r.store,
        purchased_at=r.purchased_at,
        total=r.total,
        status=r.status,
        review_reason=r.review_reason,
        user_id=r.user_id,
        user_name=r.user.name if r.user else None,
        items_count=len(r.items),
        has_image=bool(r.image_path),
        note=r.note,
        import_id=r.import_id,
        created_at=r.created_at,
    )


def to_detail(r: Receipt) -> ReceiptDetail:
    return ReceiptDetail(
        **to_out(r),
        items=[ItemOut.model_validate(i, from_attributes=True) for i in r.items],
        llm_model=r.llm_model,
        qr_raw=r.qr_raw,
        items_sum=round(sum(i.total for i in r.items), 2),
    )


async def load_receipt(session: AsyncSession, rid: int) -> Receipt:
    r = await session.get(Receipt, rid, populate_existing=True)
    if not r:
        raise HTTPException(404, "Чек не найден")
    return r


def end_of(d: date | None) -> datetime | None:
    return datetime.combine(d + timedelta(days=1), datetime.min.time()) if d else None


def start_of(d: date | None) -> datetime | None:
    return datetime.combine(d, datetime.min.time()) if d else None


# ---------- receipts ----------


@router.get("/receipts")
async def list_receipts(
    session: AsyncSession = Depends(get_session),
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    store: str | None = None,
    status: str | None = None,
    source: str | None = None,
    # a category id, or "none" for records without a category
    category_id: str | None = None,
    # records of one bank statement import
    import_id: str | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    conds = []
    if user_id:
        conds.append(Receipt.user_id == user_id)
    if date_from:
        conds.append(Receipt.purchased_at >= start_of(date_from))
    if date_to:
        conds.append(Receipt.purchased_at < end_of(date_to))
    if store:
        conds.append(icontains(Receipt.store, store))
    if status:
        conds.append(Receipt.status == status)
    if source:
        conds.append(Receipt.source == source)
    if import_id:
        conds.append(Receipt.import_id == import_id)
    if category_id == "none":
        conds.append(Receipt.items.any(Item.category_id.is_(None)))
    elif category_id:
        if not category_id.isdigit():
            raise HTTPException(400, "Неверная категория")
        cid = int(category_id)
        ids = [cid, *await session.scalars(select(Category.id).where(Category.parent_id == cid))]
        conds.append(Receipt.items.any(Item.category_id.in_(ids)))
    if q:
        conds.append(
            or_(
                icontains(Receipt.store, q),
                icontains(Receipt.note, q),
                Receipt.items.any(or_(icontains(Item.name_original, q), icontains(Item.name_ru, q))),
            )
        )
    total = await session.scalar(select(func.count(Receipt.id)).where(*conds))
    rows = await session.scalars(
        select(Receipt)
        .where(*conds)
        .order_by(Receipt.purchased_at.desc().nulls_first(), Receipt.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {"total": total, "items": [ReceiptOut(**to_out(r)) for r in rows.unique()]}


@router.get("/receipts/{rid}", response_model=ReceiptDetail)
async def get_receipt(rid: int, session: AsyncSession = Depends(get_session)):
    return to_detail(await load_receipt(session, rid))


@router.get("/receipts/{rid}/image")
async def get_image(rid: int, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    path = ReceiptService(session).image_abspath(r)
    if not path or not path.exists():
        raise HTTPException(404, "Фото нет")
    media = "image/heic" if path.suffix.lower() in {".heic", ".heif"} else None
    return FileResponse(path, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@router.patch("/receipts/{rid}", response_model=ReceiptDetail)
async def patch_receipt(rid: int, data: ReceiptPatch, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    fields = data.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] not in {"ok", "needs_review", "pending", "failed"}:
        raise HTTPException(400, "Неверный статус")
    note = fields.pop("note", None)
    note_given = "note" in data.model_fields_set and (note or None) != r.note
    for k, v in fields.items():
        setattr(r, k, v)
    if note_given:
        # same as replying to the bot: a one-line record takes the description as its name
        await ReceiptService(session).set_description(r, note or "")
    if fields.get("status") == "ok":
        r.review_reason = None
    await session.commit()
    return to_detail(await load_receipt(session, rid))


@router.delete("/receipts/{rid}")
async def delete_receipt(rid: int, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    await ReceiptService(session).delete_receipt(r)
    return {"ok": True}


@router.post("/receipts/{rid}/reprocess", response_model=ReceiptDetail)
async def reprocess(rid: int, data: ReprocessIn, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    res = await ReceiptService(session).reprocess(r, [data.model] if data.model else None)
    if res.error and not res.receipt:
        raise HTTPException(400, res.error)
    return to_detail(await load_receipt(session, rid))


@router.post("/receipts/manual", response_model=ReceiptDetail)
async def add_manual(
    data: ManualIn,
    session: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(current_viewer),
):
    r = await ReceiptService(session).book_single(
        name=(data.name or "").strip() or NO_DESCRIPTION,
        amount=data.amount,
        category_id=data.category_id,
        user_id=data.user_id or viewer.user_id,
        source="manual",
        purchased_at=data.purchased_at,
        store=data.store,
    )
    return to_detail(await load_receipt(session, r.id))


# ---------- items ----------


@router.post("/receipts/{rid}/items", response_model=ReceiptDetail)
async def add_item(rid: int, data: ItemIn, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    pos = max((i.position for i in r.items), default=-1) + 1
    session.add(
        Item(
            receipt_id=r.id,
            position=pos,
            name_original=data.name_original,
            name_ru=data.name_ru,
            name_normalized=normalize_name(data.name_original),
            qty=data.qty or 1,
            unit_price=data.unit_price if data.unit_price is not None else round2(data.total / (data.qty or 1)),
            total=data.total,
            category_id=data.category_id,
        )
    )
    await session.commit()
    return to_detail(await load_receipt(session, rid))


@router.patch("/items/{item_id}", response_model=ReceiptDetail)
async def patch_item(item_id: int, data: ItemPatch, session: AsyncSession = Depends(get_session)):
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Позиция не найдена")
    fields = data.model_dump(exclude_unset=True, exclude={"remember"})
    category_changed = "category_id" in fields and fields["category_id"] != item.category_id
    for k, v in fields.items():
        setattr(item, k, v)
    if "name_original" in fields:
        item.name_normalized = normalize_name(item.name_original)
    if "warranty_until" in fields:
        item.warranty_notified = False
    if category_changed and item.category_id and data.remember:
        await ReceiptService(session).remember_category(
            item.name_normalized, item.category_id, apply_existing=True
        )
    await session.commit()
    return to_detail(await load_receipt(session, item.receipt_id))


@router.delete("/items/{item_id}", response_model=ReceiptDetail)
async def delete_item(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Позиция не найдена")
    rid = item.receipt_id
    await session.delete(item)
    await session.commit()
    return to_detail(await load_receipt(session, rid))


# ---------- export ----------


@router.get("/export.csv")
async def export_csv(
    session: AsyncSession = Depends(get_session),
    date_from: date | None = None,
    date_to: date | None = None,
):
    Parent = aliased(Category)
    q = (
        select(Item, Receipt, User.name, Category.name, Parent.name)
        .join(Receipt, Item.receipt_id == Receipt.id)
        .outerjoin(User, Receipt.user_id == User.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .outerjoin(Parent, Category.parent_id == Parent.id)
        .order_by(Receipt.purchased_at, Receipt.id, Item.position)
    )
    if date_from:
        q = q.where(Receipt.purchased_at >= start_of(date_from))
    if date_to:
        q = q.where(Receipt.purchased_at < end_of(date_to))
    rows = (await session.execute(q)).unique().all()

    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel detects UTF-8
    w = csv.writer(buf, delimiter=";")
    w.writerow(
        ["Дата", "Магазин", "Кто", "Позиция (оригинал)", "Позиция", "Кол-во", "Цена",
         "Сумма, €", "Категория", "Подкатегория", "Чек №", "Источник"]
    )
    for item, r, user_name, cat, parent in rows:
        w.writerow(
            [
                r.purchased_at.strftime("%Y-%m-%d %H:%M") if r.purchased_at else "",
                r.store or "",
                user_name or "",
                item.name_original,
                item.name_ru or "",
                str(item.qty).replace(".", ","),
                f"{item.unit_price:.2f}".replace(".", ",") if item.unit_price is not None else "",
                f"{item.total:.2f}".replace(".", ","),
                parent or cat or "",
                cat if parent else "",
                r.id,
                r.source,
            ]
        )
    buf.seek(0)
    name = f"expenses-{date.today():%Y%m%d}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
