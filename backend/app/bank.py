"""Bank notifications (forwarded SMS/push) and bank statements (CSV/PDF).

A bank message becomes an expense record (source "bank"), unless the same amount is already
recorded around the same date: then it is only reported as a match.
"""

import csv
import hashlib
import io
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Receipt, User
from app.llm.schema import ParsedBankTx
from app.receipts.service import ReceiptService, now_local

MATCH_DAYS = 2
MATCH_TOLERANCE = 0.01

_AMOUNT = re.compile(r"\d+[.,]\d{2}\s*(?:€|eur|евро|лв|bgn)|(?:€|eur)\s*\d", re.IGNORECASE)
_BANK_WORDS = re.compile(
    r"карт|card|pos|плащане|покупка|покупк|оплата|списан|transaction|payment|трансакц|транзакц|"
    r"debit|дебит|теглене|withdraw|изтеглен|превод|transfer",
    re.IGNORECASE,
)


def looks_like_bank_message(text: str) -> bool:
    """Cheap check before asking the LLM: an amount in a currency plus a banking word."""
    return bool(text and _AMOUNT.search(text) and _BANK_WORDS.search(text))


_STATEMENT_WORDS = re.compile(
    r"выписк|извлечение|statement|kontoauszug|баланс|balance|остат|салдо|начален|opening|closing",
    re.IGNORECASE,
)
_IBAN = re.compile(r"\bIBAN\b|\b[A-Z]{2}\d{2}[A-Z]{4}\d{10,26}\b")


def looks_like_statement(text: str) -> bool:
    """A bank statement, not a receipt: an IBAN plus statement words ("выписка", "баланс")."""
    words = {m.lower()[:5] for m in _STATEMENT_WORDS.findall(text or "")}
    return bool(text and _IBAN.search(text) and words) or len(words) >= 3


def tx_external_id(tx: ParsedBankTx) -> str:
    key = f"{tx.date:%Y-%m-%d %H:%M}" if tx.date else ""
    raw = f"{key}|{tx.amount:.2f}|{(tx.merchant or '').lower()}|{tx.card or ''}"
    return "bank:" + hashlib.sha1(raw.encode()).hexdigest()


async def owner_by_card(session: AsyncSession, card: str | None) -> User | None:
    if not card:
        return None
    for u in await session.scalars(select(User).where(User.cards.is_not(None))):
        if card in {c.strip()[-4:] for c in (u.cards or "").split(",") if c.strip()}:
            return u
    return None


async def find_match(session: AsyncSession, amount: float, when: datetime | None) -> Receipt | None:
    """An already recorded expense with the same total around the same date."""
    when = when or now_local()
    q = (
        select(Receipt)
        .where(
            Receipt.total.between(amount - MATCH_TOLERANCE, amount + MATCH_TOLERANCE),
            Receipt.purchased_at.between(when - timedelta(days=MATCH_DAYS), when + timedelta(days=MATCH_DAYS)),
            Receipt.status != "failed",
        )
        .order_by(Receipt.purchased_at)
    )
    return (await session.scalars(q)).first()


@dataclass
class BankResult:
    tx: ParsedBankTx
    receipt: Receipt | None = None  # booked now
    match: Receipt | None = None  # already recorded before, nothing booked


async def book_tx(
    svc: ReceiptService,
    tx: ParsedBankTx,
    owner: User | None,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
    import_id: str | None = None,
) -> Receipt:
    name = tx.merchant or "Оплата картой"
    category_id = await svc.classify(name, tx.amount) if tx.merchant else None
    return await svc.book_single(
        name=name,
        amount=tx.amount,
        category_id=category_id,
        user_id=owner.id if owner else None,
        source="bank",
        purchased_at=tx.date,
        store=tx.merchant,
        note=f"Карта *{tx.card}" if tx.card else None,
        chat_id=chat_id,
        message_id=message_id,
        external_id=tx_external_id(tx),
        import_id=import_id,
    )


async def handle_bank_text(
    svc: ReceiptService,
    text: str,
    sender: User | None,
    *,
    chat_id: int | None = None,
    message_id: int | None = None,
) -> list[BankResult]:
    """Forwarded bank notification -> records. The card owner (Settings → Семья) wins over the
    sender."""
    res = await svc.llm.parse_bank(text)
    out: list[BankResult] = []
    for tx in res.data.transactions:
        if not tx.is_expense or tx.amount <= 0:
            continue
        ext = tx_external_id(tx)
        existing = await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext))
        match = existing or await find_match(svc.session, tx.amount, tx.date)
        if match:
            out.append(BankResult(tx=tx, match=match))
            continue
        owner = await owner_by_card(svc.session, tx.card) or sender
        out.append(BankResult(tx=tx, receipt=await book_tx(svc, tx, owner, chat_id=chat_id, message_id=message_id)))
    return out


def new_import_id() -> str:
    return f"{now_local():%Y%m%d%H%M%S}-{secrets.token_hex(3)}"


async def book_statement(
    svc: ReceiptService,
    txs: list[ParsedBankTx],
    sender: User | None,
    *,
    chat_id: int | None = None,
    import_id: str | None = None,
) -> tuple[list[Receipt], int]:
    """Books statement expenses that are not recorded yet. Returns (booked, skipped).
    All of them get one import_id."""
    import_id = import_id or new_import_id()
    booked: list[Receipt] = []
    skipped = 0
    for tx in txs:
        if not tx.is_expense or tx.amount <= 0:
            continue
        ext = tx_external_id(tx)
        if await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext)) or await find_match(
            svc.session, tx.amount, tx.date
        ):
            skipped += 1
            continue
        owner = await owner_by_card(svc.session, tx.card) or sender
        booked.append(await book_tx(svc, tx, owner, chat_id=chat_id, import_id=import_id))
    return booked, skipped


# ---------- statements ----------


def statement_text(data: bytes, filename: str) -> str:
    """CSV/TXT/PDF statement -> plain text for the LLM."""
    name = filename.lower()
    if name.endswith(".pdf") or data[:4] == b"%PDF":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        if not text.strip():
            raise ValueError("В PDF нет текста (похоже на скан). Выгрузите выписку в CSV.")
        return text
    for enc in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if name.endswith(".csv"):
        # normalise separators so the model sees a clean table
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=";,\t")
            rows = list(csv.reader(io.StringIO(text), dialect))
            text = "\n".join(" | ".join(c.strip() for c in r) for r in rows if any(c.strip() for c in r))
        except csv.Error:
            pass
    return text


@dataclass
class StatementRow:
    tx: ParsedBankTx
    external_id: str
    owner: User | None
    match: Receipt | None
    imported: bool


async def analyse_statement(svc: ReceiptService, text: str) -> list[StatementRow]:
    res = await svc.llm.parse_bank(text)
    rows: list[StatementRow] = []
    for tx in res.data.transactions:
        if not tx.is_expense or tx.amount <= 0:
            continue
        ext = tx_external_id(tx)
        imported = await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext))
        rows.append(
            StatementRow(
                tx=tx,
                external_id=ext,
                owner=await owner_by_card(svc.session, tx.card),
                match=imported or await find_match(svc.session, tx.amount, tx.date),
                imported=imported is not None,
            )
        )
    return rows


# ---------- imports (records booked from one statement) ----------


@dataclass
class ImportInfo:
    import_id: str
    created_at: datetime | None
    count: int
    total: float
    date_from: datetime | None
    date_to: datetime | None
    from_bot: bool


async def list_imports(session: AsyncSession) -> list[ImportInfo]:
    q = (
        select(
            Receipt.import_id,
            func.min(Receipt.created_at),
            func.count(Receipt.id),
            func.coalesce(func.sum(Receipt.total), 0),
            func.min(Receipt.purchased_at),
            func.max(Receipt.purchased_at),
            func.max(Receipt.chat_id),
        )
        .where(Receipt.import_id.is_not(None))
        .group_by(Receipt.import_id)
        .order_by(func.min(Receipt.created_at).desc())
    )
    return [
        ImportInfo(iid, created, count, round(total, 2), d1, d2, chat is not None)
        for iid, created, count, total, d1, d2, chat in await session.execute(q)
    ]


async def delete_import(session: AsyncSession, import_id: str) -> int:
    """Deletes every record of one statement import. Returns how many."""
    rows = list(await session.scalars(select(Receipt).where(Receipt.import_id == import_id)))
    for r in rows:
        await session.delete(r)
    await session.commit()
    return len(rows)
