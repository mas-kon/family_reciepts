"""AI features in the web UI: questions, bank statements, product grouping, warranties."""

from datetime import datetime

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
from app.db.models import Item, Receipt, User
from app.db.session import get_session
from app.llm.client import LLMClient, LLMError
from app.llm.schema import ParsedBankTx
from app.receipts.service import ReceiptService, now_local

router = APIRouter(prefix="/api", tags=["ai"], dependencies=[Depends(current_viewer)])

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


# ---------- questions ----------


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


@router.post("/ask")
async def ask(data: AskIn, session: AsyncSession = Depends(get_session)):
    try:
        return await answer(session, data.question, data.history)
    except LLMError as e:
        raise HTTPException(502, f"Нейросеть не ответила: {e}")


# ---------- bank statements ----------


def _receipt_brief(r: Receipt | None) -> dict | None:
    if not r:
        return None
    return {
        "id": r.id,
        "title": r.store or r.note or "Запись",
        "purchased_at": r.purchased_at,
        "total": r.total,
        "source": r.source,
    }


@router.post("/bank/statement")
async def bank_statement(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    """Reads a statement and shows which expenses are not recorded yet. Nothing is saved."""
    data = await file.read()
    if len(data) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, "Файл больше 5 МБ")
    try:
        text = statement_text(data, file.filename or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    svc = ReceiptService(session)
    try:
        rows = await analyse_statement(svc, text)
    except LLMError as e:
        raise HTTPException(502, f"Нейросеть не ответила: {e}")
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


class StatementImport(BaseModel):
    transactions: list[StatementTx]


@router.post("/bank/import")
async def bank_import(
    data: StatementImport,
    session: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(current_viewer),
):
    svc = ReceiptService(session)
    booked = skipped = 0
    import_id = new_import_id()
    for t in data.transactions:
        tx = ParsedBankTx(amount=t.amount, merchant=t.merchant, date=t.date, card=t.card)
        if await session.scalar(select(Receipt.id).where(Receipt.external_id == tx_external_id(tx))):
            skipped += 1
            continue
        owner = await session.get(User, t.owner_id or viewer.user_id) if (t.owner_id or viewer.user_id) else None
        await book_tx(svc, tx, owner, import_id=import_id)
        booked += 1
    return {"booked": booked, "skipped": skipped, "import_id": import_id if booked else None}


@router.get("/bank/imports")
async def bank_imports(session: AsyncSession = Depends(get_session)):
    """Statements imported so far (from the web or the bot), newest first."""
    return [i.__dict__ for i in await list_imports(session)]


@router.delete("/bank/imports/{import_id}")
async def bank_import_delete(import_id: str, session: AsyncSession = Depends(get_session)):
    deleted = await delete_import(session, import_id)
    if not deleted:
        raise HTTPException(404, "Такой выписки нет")
    return {"deleted": deleted}


# ---------- products ----------


class MergeIn(BaseModel):
    keys: list[str] = Field(min_length=1)
    product: str = Field(min_length=1, max_length=300)


@router.post("/products/merge")
async def products_merge(data: MergeIn, session: AsyncSession = Depends(get_session)):
    return {"lines": await products_mod.merge(session, data.keys, data.product)}


class SplitIn(BaseModel):
    key: str


@router.post("/products/split")
async def products_split(data: SplitIn, session: AsyncSession = Depends(get_session)):
    return {"lines": await products_mod.split(session, data.key)}


@router.post("/products/group")
async def products_group(session: AsyncSession = Depends(get_session)):
    """Groups every not yet grouped product name with the LLM."""
    return {"grouped": await products_mod.group_names(session, LLMClient())}


# ---------- warranties ----------


@router.get("/warranties")
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
    ]

