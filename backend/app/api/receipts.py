import asyncio
import csv
import io
import logging
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, noload

from app.api.ai import ReceiptBrief, _receipt_brief
from app.api.deps import Viewer, current_viewer
from app.api.schemas import Ok
from app.bank import looks_like_statement, statement_text
from app.clock import now_local
from app.config import get_settings
from app.constants import Kind, income_default, no_description
from app.db.models import Category, Item, Receipt, User
from app.db.session import get_session, icontains
from app.i18n import t
from app.llm.slots import llm_slots
from app.receipts.money import round2
from app.receipts.service import ReceiptService
from app.receipts.text import normalize_name
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["receipts"], dependencies=[Depends(current_viewer)])

MAX_PHOTO_BYTES = 25 * 1024 * 1024


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
    source: Literal["photo", "manual", "recurring", "bank", "voice", "email"]
    store: str | None
    purchased_at: datetime | None
    total: float | None
    status: Literal["ok", "needs_review", "pending", "failed"]
    review_reason: str | None
    user_id: int | None
    user_name: str | None
    items_count: int
    has_image: bool
    note: str | None
    import_id: str | None
    kind: Kind
    counterparty: str | None
    peer_user_id: int | None
    peer_name: str | None
    created_at: datetime


class ReceiptDetail(ReceiptOut):
    items: list[ItemOut]
    llm_model: str | None
    qr_raw: str | None
    items_sum: float


class ReceiptPage(BaseModel):
    total: int
    items: list[ReceiptOut]


class ReceiptPatch(BaseModel):
    store: str | None = None
    purchased_at: datetime | None = None
    total: float | None = None
    status: Literal["ok", "needs_review", "pending", "failed"] | None = None
    note: str | None = None
    user_id: int | None = None
    kind: Kind | None = None
    # family member on the other side of a transfer
    peer_user_id: int | None = None
    # remember the counterparty as this member's name in the bank: their transfers are always
    # inside the family, including the ones recorded before
    remember_peer: bool = False


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
    kind: str = Field("expense", pattern="^(expense|income)$")


class UploadOut(BaseModel):
    status: Literal["ok", "needs_review", "failed", "duplicate", "maybe_duplicate", "not_receipt", "statement"]
    receipt: ReceiptDetail | None
    duplicate_of: ReceiptBrief | None
    alerts: list[str]


class ReprocessIn(BaseModel):
    model: str | None = None


def kind_label(kind: str) -> str:
    return t(f"kind.{kind}") if kind in ("expense", "income", "transfer") else kind


# ---------- helpers ----------


def to_out(r: Receipt, items_count: int | None = None, first_name: str | None = None) -> dict:
    """A list row passes the count and the first line's name: the items are not loaded for it."""
    if items_count is None:
        first = r.items[0] if r.items else None
        first_name = first.name_ru or first.name_original if first else None
        items_count = len(r.items)
    title = r.store or r.note or first_name or t("bot.receipt")
    return {
        "id": r.id,
        "title": title,
        "source": r.source,
        "store": r.store,
        "purchased_at": r.purchased_at,
        "total": r.total,
        "status": r.status,
        "review_reason": r.review_reason,
        "user_id": r.user_id,
        "user_name": r.user.name if r.user else None,
        "items_count": items_count,
        "has_image": bool(r.image_path),
        "note": r.note,
        "import_id": r.import_id,
        "kind": r.kind,
        "counterparty": r.counterparty,
        "peer_user_id": r.peer_user_id,
        "peer_name": r.peer.name if r.peer else None,
        "created_at": r.created_at,
    }


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
        raise HTTPException(404, t("api.receipt_not_found"))
    return r


async def ensure_exists(session: AsyncSession, model, obj_id: int | None, what: str) -> None:
    """404/400 instead of a foreign key error (500) for an id that does not exist."""
    if obj_id is not None and await session.get(model, obj_id) is None:
        raise HTTPException(400, t("api.not_found_named", what=what))


def end_of(d: date | None) -> datetime | None:
    return datetime.combine(d + timedelta(days=1), datetime.min.time()) if d else None


def start_of(d: date | None) -> datetime | None:
    return datetime.combine(d, datetime.min.time()) if d else None


# ---------- receipts ----------


@router.get("/receipts", response_model=ReceiptPage)
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
    # expense | income | transfer
    kind: str | None = None,
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
    if kind:
        conds.append(Receipt.kind == kind)
    if category_id == "none":
        conds.append(Receipt.items.any(Item.category_id.is_(None)))
    elif category_id:
        if not category_id.isdigit():
            raise HTTPException(400, t("api.bad_category"))
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
    rows = list(
        (
            await session.scalars(
                select(Receipt)
                .options(noload(Receipt.items))  # a list needs only the count and one name
                .where(*conds)
                .order_by(Receipt.purchased_at.desc().nulls_first(), Receipt.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).unique()
    )
    ids = [r.id for r in rows]
    counts = {
        rid: n
        for rid, n in await session.execute(
            select(Item.receipt_id, func.count()).where(Item.receipt_id.in_(ids)).group_by(Item.receipt_id)
        )
    }
    first_names = {
        rid: name_ru or name_original
        for rid, name_ru, name_original in await session.execute(
            select(Item.receipt_id, Item.name_ru, Item.name_original).where(
                Item.receipt_id.in_(ids), Item.position == 0
            )
        )
    }
    return {
        "total": total,
        "items": [ReceiptOut(**to_out(r, counts.get(r.id, 0), first_names.get(r.id))) for r in rows],
    }


@router.get("/receipts/{rid}", response_model=ReceiptDetail)
async def get_receipt(rid: int, session: AsyncSession = Depends(get_session)):
    return to_detail(await load_receipt(session, rid))


@router.get("/receipts/{rid}/image")
async def get_image(rid: int, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    path = ReceiptService(session).image_abspath(r)
    if not path or not path.exists():
        raise HTTPException(404, t("api.no_photo"))
    media = "image/heic" if path.suffix.lower() in {".heic", ".heif"} else None
    return FileResponse(
        path, media_type=media, headers={"Cache-Control": "private, no-cache"}
    )  # revalidate (ETag): an id can be reused


@router.patch("/receipts/{rid}", response_model=ReceiptDetail)
async def patch_receipt(rid: int, data: ReceiptPatch, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    fields = data.model_dump(exclude_unset=True)
    await ensure_exists(session, User, fields.get("user_id"), t("api.member"))
    note = fields.pop("note", None)
    note_given = "note" in data.model_fields_set and (note or None) != r.note
    kind = fields.pop("kind", None)
    peer_id = fields.pop("peer_user_id", None)
    remember = fields.pop("remember_peer", False)
    svc = ReceiptService(session)
    if kind:
        peer = await session.get(User, peer_id) if peer_id else None
        if kind == Kind.TRANSFER and peer_id and not peer:
            raise HTTPException(404, t("api.member_not_found"))
        await svc.set_kind(r, kind, peer)
        if remember and peer and r.counterparty:
            await svc.remember_bank_name(peer, r.counterparty)
    for k, v in fields.items():
        setattr(r, k, v)
    if fields.get("status") == "ok":
        r.review_reason = None
    await session.commit()  # all plain edits in one transaction
    if note_given:
        # same as replying to the bot: a one-line record takes the description as its name
        # (may ask the model, so it comes after the commit: no write lock while waiting)
        await svc.set_description(r, note or "")
    return to_detail(await load_receipt(session, rid))


@router.delete("/receipts/{rid}", response_model=Ok)
async def delete_receipt(rid: int, session: AsyncSession = Depends(get_session)):
    r = await load_receipt(session, rid)
    await ReceiptService(session).delete_receipt(r)
    return Ok()


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
    await ensure_exists(session, Category, data.category_id, t("api.category"))
    await ensure_exists(session, User, data.user_id, t("api.member"))
    svc = ReceiptService(session)
    name = (data.name or "").strip() or (income_default() if data.kind == Kind.INCOME else no_description())
    category_id = data.category_id
    if data.kind == Kind.INCOME and category_id is None:
        category_id = await svc.income_category(name)
    r = await svc.book_single(
        name=name,
        amount=data.amount,
        kind=data.kind,
        category_id=category_id,
        user_id=data.user_id or viewer.user_id,
        source="manual",
        purchased_at=data.purchased_at,
        store=data.store,
    )
    return to_detail(await load_receipt(session, r.id))


@router.post("/receipts/upload", response_model=UploadOut)
async def upload_receipt(
    request: Request,
    file: UploadFile = File(...),
    client_id: str = Form(pattern=r"^[0-9A-Za-z-]{8,64}$"),
    note: str | None = Form(None),
    user_id: int | None = Form(None),
    session: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(current_viewer),
):
    """A receipt picture or PDF from the web app. Waits for recognition, like the bot does.
    `client_id` makes a repeated request (a lost connection) return the same record as a duplicate."""
    if file.size is not None and file.size > MAX_PHOTO_BYTES:
        raise HTTPException(413, t("api.file_too_big_photo"))
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, t("api.file_too_big_photo"))
    await ensure_exists(session, User, user_id, t("api.member"))
    owner_id = user_id or viewer.user_id
    owner = await session.get(User, owner_id) if owner_id else None
    name = (file.filename or "").lower()
    is_pdf = file.content_type == "application/pdf" or name.endswith(".pdf")
    ext = (file.content_type or "").split("/")[-1].replace("jpeg", "jpg") if file.content_type else ""
    if not ext.isalnum() or ext == "octet-stream":
        ext = name.rsplit(".", 1)[-1] if "." in name else "jpg"
    external_id = f"web:{client_id}"
    note = (note or "").strip() or None

    svc = ReceiptService(session)
    async with llm_slots:
        if is_pdf:
            try:
                text = await asyncio.to_thread(statement_text, data, "x.pdf")
            except Exception:
                text = ""  # a scan: read it as a receipt picture
            if looks_like_statement(text):
                return UploadOut(status="statement", receipt=None, duplicate_of=None, alerts=[])
            res = await svc.process_pdf(data, owner, external_id=external_id, note=note)
        else:
            res = await svc.process_photo(data, owner, ext=ext, note=note, external_id=external_id)

    if res.duplicate_of:
        return UploadOut(status="duplicate", receipt=None, duplicate_of=_receipt_brief(res.duplicate_of), alerts=[])
    if res.not_receipt:
        return UploadOut(status="not_receipt", receipt=None, duplicate_of=None, alerts=[])
    receipt = res.receipt
    if receipt is None:
        return UploadOut(status="failed", receipt=None, duplicate_of=None, alerts=[])
    await session.commit()
    detail = to_detail(await load_receipt(session, receipt.id))
    if res.error or receipt.status == "failed":
        return UploadOut(status="failed", receipt=detail, duplicate_of=None, alerts=[])
    if res.maybe_duplicate_of:
        return UploadOut(
            status="maybe_duplicate",
            receipt=detail,
            duplicate_of=_receipt_brief(res.maybe_duplicate_of),
            alerts=[],
        )
    alerts = await new_budget_alerts(session, receipt)
    bot = getattr(request.app.state, "bot", None)
    chat = get_settings().notify_chat_id
    if bot and chat:
        for a in alerts:
            try:
                await bot.send_message(chat, a)
            except Exception:
                log.exception("failed to send a budget alert")
    status = "needs_review" if receipt.status == "needs_review" else "ok"
    return UploadOut(status=status, receipt=detail, duplicate_of=None, alerts=alerts)


# ---------- items ----------


@router.post("/receipts/{rid}/items", response_model=ReceiptDetail)
async def add_item(rid: int, data: ItemIn, session: AsyncSession = Depends(get_session)):
    await ensure_exists(session, Category, data.category_id, t("api.category"))
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
        raise HTTPException(404, t("api.item_not_found"))
    fields = data.model_dump(exclude_unset=True, exclude={"remember"})
    await ensure_exists(session, Category, fields.get("category_id"), t("api.category"))
    category_changed = "category_id" in fields and fields["category_id"] != item.category_id
    for k, v in fields.items():
        setattr(item, k, v)
    if "name_original" in fields:
        item.name_normalized = normalize_name(item.name_original)
    if "warranty_until" in fields:
        item.warranty_notified = False
    if category_changed and item.category_id and data.remember:
        await ReceiptService(session).remember_category(item.name_normalized, item.category_id, apply_existing=True)
    await session.commit()
    return to_detail(await load_receipt(session, item.receipt_id))


@router.delete("/items/{item_id}", response_model=ReceiptDetail)
async def delete_item(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(Item, item_id)
    if not item:
        raise HTTPException(404, t("api.item_not_found"))
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
    buf.write("\ufeff")  # BOM so Excel detects UTF-8
    w = csv.writer(buf, delimiter=";")
    w.writerow(
        [
            t("csv.date"),
            t("csv.store"),
            t("csv.who"),
            t("csv.item_original"),
            t("csv.item"),
            t("csv.qty"),
            t("csv.price"),
            t("csv.total"),
            t("csv.category"),
            t("csv.subcategory"),
            t("csv.receipt_no"),
            t("csv.source"),
            t("csv.type"),
        ]
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
                kind_label(r.kind),
            ]
        )
    buf.seek(0)
    name = f"expenses-{now_local():%Y%m%d}.csv"
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
