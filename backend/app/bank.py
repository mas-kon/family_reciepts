"""Bank notifications (forwarded SMS/push) and bank statements (CSV/PDF).

Every operation becomes a record (source "bank") of one kind:
- expense: a purchase, a fee, a transfer to someone outside the family;
- income: salary, a refund, money from someone outside the family;
- transfer: money sent to or received from a family member (Settings → Семья → name in the bank).
  Counted neither as spent nor as earned, so a child's pocket money is not spent twice.
Moves between own accounts and top-ups from an own card are not booked at all.
An operation whose amount is already recorded around the same date is only reported as a match.
"""

import csv
import hashlib
import io
import re
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_local
from app.constants import INCOME_DEFAULT, Kind
from app.db.models import Receipt, User
from app.family import family_by_bank_name, owner_by_card
from app.llm.schema import ParsedBankTx
from app.receipts.service import ReceiptService
from app.receipts.text import normalize_name

MATCH_DAYS = 2
MATCH_TOLERANCE = 0.01

_AMOUNT = re.compile(r"\d+[.,]\d{2}\s*(?:€|eur|евро|лв|bgn)|(?:€|eur)\s*\d", re.IGNORECASE)
_BANK_WORDS = re.compile(
    r"карт|card|pos|плащане|покупка|покупк|оплата|списан|transaction|payment|трансакц|транзакц|"
    r"debit|дебит|теглене|withdraw|изтеглен|превод|transfer|"
    r"постъплен|получен|зачислен|поступлен|пополнен|received|incoming|credit|кредит|заплата|зарплат",
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


def tx_external_id(tx: ParsedBankTx, occurrence: int = 0) -> str:
    key = f"{tx.date:%Y-%m-%d %H:%M}" if tx.date else ""
    raw = f"{key}|{tx.amount:.2f}|{(tx.merchant or '').lower()}|{tx.card or ''}"
    if occurrence:
        raw += f"|{occurrence}"  # the 2nd identical operation in one batch is a separate purchase
    return "bank:" + hashlib.sha1(raw.encode()).hexdigest()


def external_ids(txs: list[ParsedBankTx]) -> list[str]:
    """Ids for a batch: identical operations (same minute or day, amount, shop, card) get
    different ids, but loading the same batch again gives the same ids, so it stays idempotent."""
    seen: Counter[str] = Counter()
    out = []
    for tx in txs:
        base = tx_external_id(tx)
        out.append(tx_external_id(tx, seen[base]))
        seen[base] += 1
    return out


@dataclass
class TxPlan:
    """How one bank operation is booked. kind None: not booked (own money moved)."""

    kind: str | None
    peer: User | None = None


async def plan_tx(session: AsyncSession, tx: ParsedBankTx) -> TxPlan:
    if tx.type == "own":
        return TxPlan(None)
    if tx.type in {"transfer_out", "transfer_in"} and (peer := await family_by_bank_name(session, tx.counterparty)):
        return TxPlan("transfer", peer)
    return TxPlan("expense" if tx.outgoing else "income")


async def find_match(
    session: AsyncSession,
    amount: float,
    when: datetime | None,
    kind: Kind = Kind.EXPENSE,
    *,
    merchant: str | None = None,
    import_id: str | None = None,
    batch_ids: set[str] | None = None,
) -> Receipt | None:
    """An already recorded operation of this kind with the same total around the same date.

    Records of another source (a receipt photo, a manual entry) match by amount and date. A
    bank record matches only the same shop on the same day, and never one from the statement
    being imported: two coffees of 2.50 on consecutive days are two purchases."""
    when = when or now_local()
    q = (
        select(Receipt)
        .where(
            Receipt.kind == kind,
            Receipt.total.between(amount - MATCH_TOLERANCE, amount + MATCH_TOLERANCE),
            Receipt.purchased_at.between(when - timedelta(days=MATCH_DAYS), when + timedelta(days=MATCH_DAYS)),
            Receipt.status != "failed",
        )
        .order_by(Receipt.purchased_at)
    )
    shop = normalize_name(merchant or "")
    for r in await session.scalars(q):
        if r.source != "bank":
            return r
        if (import_id and r.import_id == import_id) or r.external_id in (batch_ids or ()):
            continue  # an exact operation of this very batch, not a receipt of the same purchase
        same_day = r.purchased_at is not None and r.purchased_at.date() == when.date()
        if same_day and shop and normalize_name(r.store or "") == shop:
            return r
    return None


@dataclass
class BankResult:
    tx: ParsedBankTx
    kind: str
    receipt: Receipt | None = None  # booked now
    match: Receipt | None = None  # already recorded before, nothing booked


async def book_tx(
    svc: ReceiptService,
    tx: ParsedBankTx,
    owner: User | None,
    *,
    kind: Kind = Kind.EXPENSE,
    peer: User | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    import_id: str | None = None,
    external_id: str | None = None,
) -> Receipt:
    if kind == Kind.TRANSFER:
        name = tx.merchant or (f"Перевод: {peer.name}" if peer else "Перевод в семье")
        category_id = None
    elif kind == Kind.INCOME:
        name = tx.merchant or INCOME_DEFAULT
        category_id = await svc.income_category(name)
    else:
        name = tx.merchant or "Оплата картой"
        # a transfer to a person has no shop to guess the category from
        category_id = await svc.classify(name, tx.amount) if tx.merchant and tx.type == "purchase" else None
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
        external_id=external_id or tx_external_id(tx),
        import_id=import_id,
        kind=kind,
        counterparty=tx.counterparty,
        peer_user_id=peer.id if peer else None,
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
    sender. Moves between own accounts are skipped."""
    res = await svc.llm.parse_bank(text)
    out: list[BankResult] = []
    txs = res.data.transactions
    ids_all = external_ids(txs)
    for tx, ext in zip(txs, ids_all):
        plan = await plan_tx(svc.session, tx)
        if plan.kind is None or tx.amount <= 0:
            continue
        existing = await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext))
        match = existing or await find_match(
            svc.session, tx.amount, tx.date, plan.kind, merchant=tx.merchant, batch_ids=set(ids_all)
        )
        if match:
            out.append(BankResult(tx=tx, kind=plan.kind, match=match))
            continue
        owner = await owner_by_card(svc.session, tx.card) or sender
        receipt = await book_tx(
            svc,
            tx,
            owner,
            kind=plan.kind,
            peer=plan.peer,
            chat_id=chat_id,
            message_id=message_id,
            external_id=ext,
        )
        out.append(BankResult(tx=tx, kind=plan.kind, receipt=receipt))
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
    ids: list[str] | None = None,
    batch_ids: set[str] | None = None,
) -> tuple[list[Receipt], int]:
    """Books statement operations that are not recorded yet. Returns (booked, skipped).
    All of them get one import_id. `ids` are the operations' external ids from the analysis
    (a subset of a statement must keep the ids it had in the whole one); `batch_ids` are the ids
    of the whole statement."""
    import_id = import_id or new_import_id()
    booked: list[Receipt] = []
    skipped = 0
    ids_all = batch_ids if batch_ids is not None else (ids or external_ids(txs))
    for tx, ext in zip(txs, ids or external_ids(txs)):
        plan = await plan_tx(svc.session, tx)
        if plan.kind is None or tx.amount <= 0:
            continue
        if await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext)) or await find_match(
            svc.session,
            tx.amount,
            tx.date,
            plan.kind,
            merchant=tx.merchant,
            import_id=import_id,
            batch_ids=set(ids_all),
        ):
            skipped += 1
            continue
        owner = await owner_by_card(svc.session, tx.card) or sender
        booked.append(
            await book_tx(
                svc,
                tx,
                owner,
                kind=plan.kind,
                peer=plan.peer,
                chat_id=chat_id,
                import_id=import_id,
                external_id=ext,
            )
        )
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
    # expense | income | transfer, None for a move between own accounts
    kind: str | None
    peer: User | None


async def analyse_statement(svc: ReceiptService, text: str) -> list[StatementRow]:
    res = await svc.llm.parse_bank(text)
    rows: list[StatementRow] = []
    txs = res.data.transactions
    ids_all = external_ids(txs)
    for tx, ext in zip(txs, ids_all):
        if tx.amount <= 0:
            continue
        plan = await plan_tx(svc.session, tx)
        imported = await svc.session.scalar(select(Receipt).where(Receipt.external_id == ext))
        match = imported
        if match is None and plan.kind:
            match = await find_match(
                svc.session, tx.amount, tx.date, plan.kind, merchant=tx.merchant, batch_ids=set(ids_all)
            )
        rows.append(
            StatementRow(
                tx=tx,
                external_id=ext,
                owner=await owner_by_card(svc.session, tx.card),
                match=match,
                imported=imported is not None,
                kind=plan.kind,
                peer=plan.peer,
            )
        )
    return rows


# ---------- imports (records booked from one statement) ----------


@dataclass
class ImportInfo:
    import_id: str
    created_at: datetime | None
    count: int
    total: float  # expenses only
    date_from: datetime | None
    date_to: datetime | None
    from_bot: bool


async def list_imports(session: AsyncSession) -> list[ImportInfo]:
    q = (
        select(
            Receipt.import_id,
            func.min(Receipt.created_at),
            func.count(Receipt.id),
            func.coalesce(func.sum(Receipt.total).filter(Receipt.kind == Kind.EXPENSE), 0),
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
