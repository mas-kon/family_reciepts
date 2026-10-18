"""AI features in the web UI: questions, bank statements, product grouping, warranties."""

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import products as products_mod
from app.api.deps import Viewer, current_viewer
from app.ask import answer
from app.bank import (
    analyse_statement,
    book_tx,
    delete_import,
    list_imports,
    new_import_id,
    statement_text,
    tx_external_id,
)
from app.clock import now_local
from app.constants import Kind
from app.db.models import Item, Receipt, User
from app.db.session import get_session
from app.i18n import t
from app.llm.client import LLMError, get_llm
from app.llm.schema import ParsedBankTx
from app.receipts.service import ReceiptService

router = APIRouter(prefix="/api", tags=["ai"], dependencies=[Depends(current_viewer)])

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


# ---------- questions ----------


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


class AskOut(BaseModel):
    answer: str
    model: str
    tools: list[str]


@router.post("/ask", response_model=AskOut)
async def ask(data: AskIn, session: AsyncSession = Depends(get_session)):
    try:
        return await answer(session, data.question, data.history)
    except LLMError as e:
        raise HTTPException(502, t("api.llm_down", error=e))


# ---------- bank statements ----------


class ReceiptBrief(BaseModel):
    id: int
    title: str
    purchased_at: datetime | None
    total: float | None
    source: str


class StatementRowOut(BaseModel):
    external_id: str
    date: datetime | None
    amount: float
    merchant: str | None
    card: str | None
    owner_id: int | None
    type: str | None
    counterparty: str | None
    # None: own money moved, not booked by default
    kind: Kind | None
    peer_id: int | None
    match: ReceiptBrief | None
    imported: bool


class StatementOut(BaseModel):
    transactions: list[StatementRowOut]


def _receipt_brief(r: Receipt | None) -> ReceiptBrief | None:
    if not r:
        return None
    return ReceiptBrief(
        id=r.id, title=r.store or r.note or t("api.record"), purchased_at=r.purchased_at, total=r.total, source=r.source
    )


@router.post("/bank/statement", response_model=StatementOut)
async def bank_statement(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    """Reads a statement and shows which expenses are not recorded yet. Nothing is saved."""
    if file.size is not None and file.size > MAX_STATEMENT_BYTES:
        raise HTTPException(413, t("api.file_too_big"))
    data = await file.read(MAX_STATEMENT_BYTES + 1)
    if len(data) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, t("api.file_too_big"))
    try:
        text = await asyncio.to_thread(statement_text, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc = ReceiptService(session)
    try:
        rows = await analyse_statement(svc, text)
    except LLMError as e:
        raise HTTPException(502, t("api.llm_down", error=e))
    return {
        "transactions": [
            {
                "external_id": r.external_id,
                "date": r.tx.date,
                "amount": r.tx.amount,
                "merchant": r.tx.merchant,
                "card": r.tx.card,
                "owner_id": r.owner.id if r.owner else None,
                "match": _receipt_brief(r.match),
                "imported": r.imported,
                "type": r.tx.type,
                "counterparty": r.tx.counterparty,
                # expense | income | transfer, null: own money moved, not booked by default
                "kind": r.kind,
                "peer_id": r.peer.id if r.peer else None,
            }
            for r in rows
        ]
    }


class StatementTx(BaseModel):
    date: datetime | None = None
    amount: float = Field(gt=0)
    merchant: str | None = None
    card: str | None = None
    owner_id: int | None = None
    type: str | None = None
    counterparty: str | None = None
    kind: Kind = Kind.EXPENSE
    # id from the analysis (identical operations of a statement differ in it)
    external_id: str | None = None
    # family member of a transfer; with a counterparty it is remembered as their name in the bank
    peer_id: int | None = None


class StatementImport(BaseModel):
    transactions: list[StatementTx]


class ImportOut(BaseModel):
    booked: int
    skipped: int
    import_id: str | None
    marked_transfers: int


@router.post("/bank/import", response_model=ImportOut)
async def bank_import(
    data: StatementImport,
    session: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(current_viewer),
):
    svc = ReceiptService(session)
    booked = skipped = 0
    import_id = new_import_id()
    remembered = 0
    for row in data.transactions:
        tx = ParsedBankTx(
            amount=row.amount, merchant=row.merchant, date=row.date, card=row.card, type=row.type, counterparty=row.counterparty
        )
        ext = row.external_id or tx_external_id(tx)
        if await session.scalar(select(Receipt.id).where(Receipt.external_id == ext)):
            skipped += 1
            continue
        owner = await session.get(User, row.owner_id or viewer.user_id) if (row.owner_id or viewer.user_id) else None
        peer = await session.get(User, row.peer_id) if row.kind == Kind.TRANSFER and row.peer_id else None
        await book_tx(svc, tx, owner, kind=row.kind, peer=peer, import_id=import_id, external_id=ext)
        booked += 1
        if peer and row.counterparty:
            remembered += await svc.remember_bank_name(peer, row.counterparty)
            await session.commit()
    return {
        "booked": booked,
        "skipped": skipped,
        "import_id": import_id if booked else None,
        "marked_transfers": remembered,
    }


class ImportInfo(BaseModel):
    import_id: str
    created_at: datetime | None
    count: int
    total: float
    date_from: datetime | None
    date_to: datetime | None
    from_bot: bool


@router.get("/bank/imports", response_model=list[ImportInfo])
async def bank_imports(session: AsyncSession = Depends(get_session)):
    """Statements imported so far (from the web or the bot), newest first."""
    return [i.__dict__ for i in await list_imports(session)]


class Deleted(BaseModel):
    deleted: int


@router.delete("/bank/imports/{import_id}", response_model=Deleted)
async def bank_import_delete(import_id: str, session: AsyncSession = Depends(get_session)):
    deleted = await delete_import(session, import_id)
    if not deleted:
        raise HTTPException(404, t("api.no_statement"))
    return {"deleted": deleted}


# ---------- products ----------


class MergeIn(BaseModel):
    keys: list[str] = Field(min_length=1)
    product: str = Field(min_length=1, max_length=300)


class Lines(BaseModel):
    lines: int


@router.post("/products/merge", response_model=Lines)
async def products_merge(data: MergeIn, session: AsyncSession = Depends(get_session)):
    return {"lines": await products_mod.merge(session, data.keys, data.product)}


class SplitIn(BaseModel):
    key: str


@router.post("/products/split", response_model=Lines)
async def products_split(data: SplitIn, session: AsyncSession = Depends(get_session)):
    return {"lines": await products_mod.split(session, data.key)}


class Queued(BaseModel):
    queued: int


@router.post("/products/group", response_model=Queued)
async def products_group(session: AsyncSession = Depends(get_session)):
    """Groups every not yet grouped product name with the LLM. Takes minutes for a long backlog,
    so it runs in the background; the lists show the result as it arrives."""
    names = await products_mod.ungrouped_names(session)
    products_mod.schedule_grouping(names, get_llm())
    return {"queued": len(names)}


# ---------- warranties ----------


class WarrantyOut(BaseModel):
    item_id: int
    name: str
    name_original: str
    total: float
    warranty_until: date
    days_left: int
    receipt_id: int
    store: str | None
    purchased_at: datetime | None
    has_image: bool


@router.get("/warranties", response_model=list[WarrantyOut])
async def warranties(expired: bool = False, session: AsyncSession = Depends(get_session)):
    today = now_local().date()
    q = (
        select(Item, Receipt)
        .join(Receipt, Item.receipt_id == Receipt.id)
        .where(Item.warranty_until.is_not(None))
        .order_by(Item.warranty_until)
    )
    if not expired:
        q = q.where(Item.warranty_until >= today)
    rows = await session.execute(q)
    return [
        {
            "item_id": it.id,
            "name": it.name_ru or it.name_original,
            "name_original": it.name_original,
            "total": it.total,
            "warranty_until": it.warranty_until,
            "days_left": (it.warranty_until - today).days,
            "receipt_id": r.id,
            "store": r.store,
            "purchased_at": r.purchased_at,
            "has_image": bool(r.image_path),
        }
        for it, r in rows
        if it.warranty_until
    ]
