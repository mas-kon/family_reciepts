"""Records that are not read from a picture: typed, spoken, recurring, bank; and edits of any record."""

import logging
from datetime import datetime

from sqlalchemy import select

from app.clock import now_local
from app.constants import INCOME_DEFAULT, NO_DESCRIPTION, PURCHASE_DEFAULT, Kind
from app.db.models import Category, CategoryOverride, Item, Receipt, User
from app.family import apply_family_names
from app.llm.client import LLMError
from app.llm.prompt import manual_system
from app.receipts.base import ServiceBase, single_item
from app.receipts.money import round2
from app.receipts.parsing import parse_manual_text
from app.receipts.text import csv_list, normalize_name

log = logging.getLogger(__name__)


class RecordsMixin(ServiceBase):
    # ---------- single-line entries (manual, recurring) ----------

    async def book_single(
        self,
        *,
        name: str,
        amount: float,
        category_id: int | None,
        user_id: int | None,
        source: str,
        purchased_at: datetime | None = None,
        store: str | None = None,
        note: str | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        external_id: str | None = None,
        import_id: str | None = None,
        kind: str = Kind.EXPENSE,
        counterparty: str | None = None,
        peer_user_id: int | None = None,
    ) -> Receipt:
        receipt = Receipt(
            source=source,
            kind=kind,
            counterparty=counterparty,
            peer_user_id=peer_user_id,
            external_id=external_id,
            import_id=import_id,
            status="ok",
            user_id=user_id,
            store=store,
            purchased_at=purchased_at or now_local(),
            total=round2(amount),
            note=note,
            chat_id=chat_id,
            message_id=message_id,
        )
        receipt.items.append(single_item(name, amount, category_id))
        self.session.add(receipt)
        await self.session.commit()
        return receipt

    async def add_income_text(
        self,
        text: str,
        user: User | None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> Receipt | None:
        """'зарплата 1500' -> income record. None when there is no amount."""
        quick = parse_manual_text(text)
        if not quick:
            return None
        name = quick[0] or INCOME_DEFAULT
        return await self.book_single(
            name=name,
            amount=quick[1],
            category_id=await self.income_category(name),
            user_id=user.id if user else None,
            source="manual",
            kind=Kind.INCOME,
            chat_id=chat_id,
            message_id=message_id,
        )

    async def add_manual_text(
        self,
        text: str,
        user: User | None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> Receipt | None:
        """Parses 'такси 12' style text. Returns None when it is not an expense line.
        A bare amount ('12') is booked without description and category."""
        quick = parse_manual_text(text)
        if quick and quick[0] is None:
            return await self.book_single(
                name=NO_DESCRIPTION,
                amount=quick[1],
                category_id=None,
                user_id=user.id if user else None,
                source="manual",
                chat_id=chat_id,
                message_id=message_id,
            )
        matcher = await self.matcher()
        name = amount = None
        category_id = None
        if quick:
            name, amount = quick
            category_id = await self.override_category(name) if name else None
        if category_id is None:
            try:
                res = await self.llm.parse_manual(text, manual_system(matcher.path_list()))
                if name is None:
                    name, amount = res.data.name, res.data.amount
                category = matcher.match(res.data.category)
            except LLMError as e:
                log.warning("manual entry LLM failed: %s", e)
                category = matcher.fallback
            category_id = category.id if category else None
        if not name or amount is None:
            return None
        return await self.book_single(
            name=name,
            amount=amount,
            category_id=category_id,
            user_id=user.id if user else None,
            source="manual",
            chat_id=chat_id,
            message_id=message_id,
        )

    async def classify(self, name: str, amount: float) -> int | None:
        """Category for a single free-text purchase: remembered choice first, then the LLM."""
        if (remembered := await self.override_category(name)) is not None:
            return remembered
        matcher = await self.matcher()
        try:
            res = await self.llm.parse_manual(f"{name} {amount}", manual_system(matcher.path_list()))
        except LLMError as e:
            log.warning("classify failed: %s", e)
            return None
        cat = matcher.match(res.data.category)
        return cat.id if cat and cat is not matcher.fallback else None

    async def set_description(self, receipt: Receipt, text: str) -> Receipt:
        """Adds a description. A one-line entry without a real name (bare amount, total-only
        receipt) also takes the description as its name and gets a category from it."""
        text = text.strip()
        receipt.note = text or None
        await self.session.commit()  # no pending writes (write lock) while classify waits for the LLM
        items = await receipt.awaitable_attrs.items
        if text and len(items) == 1 and receipt.kind == Kind.INCOME:
            it = items[0]
            if it.name_original in {NO_DESCRIPTION, INCOME_DEFAULT}:
                category_id = await self.income_category(text)
                it.name_original = it.name_ru = text[:300]
                it.name_normalized = normalize_name(text)
                it.category_id = category_id
        elif (
            text
            and len(items) == 1
            and receipt.kind == Kind.EXPENSE
            and (
                items[0].category_id is None
                or items[0].name_original in {NO_DESCRIPTION, PURCHASE_DEFAULT, receipt.store}
            )
        ):
            it = items[0]
            category_id = await self.classify(text, it.total)  # before any change: LLM, no lock
            it.name_original = it.name_ru = text[:300]
            it.name_normalized = normalize_name(text)
            it.category_id = category_id or it.category_id
        await self.session.commit()
        return receipt

    # ---------- edits from the web ----------

    async def set_kind(self, receipt: Receipt, kind: str, peer: User | None = None) -> None:
        """Expense, income or a transfer inside the family. Categories of the other kind are
        dropped, an income gets an income category. The caller commits."""
        receipt.kind = kind
        receipt.peer_user_id = peer.id if kind == Kind.TRANSFER and peer else None
        cat_kind = {c.id: c.kind for c in await self.session.scalars(select(Category))}
        for it in await receipt.awaitable_attrs.items:
            if kind == Kind.TRANSFER or (it.category_id and cat_kind.get(it.category_id) != kind):
                it.category_id = None
            if kind == Kind.INCOME and it.category_id is None:
                it.category_id = await self.income_category(it.name_original)

    async def remember_bank_name(self, member: User, name: str) -> int:
        """Transfers to/from this name are inside the family from now on, recorded ones too.
        The caller commits."""
        names = csv_list(member.bank_names)
        if normalize_name(name) not in {normalize_name(n) for n in names}:
            member.bank_names = ",".join([*names, name.strip()])
        return await apply_family_names(self.session)

    async def remember_category(self, name_normalized: str, category_id: int, apply_existing: bool):
        ov = await self.session.scalar(
            select(CategoryOverride).where(CategoryOverride.name_normalized == name_normalized)
        )
        if ov:
            ov.category_id = category_id
        else:
            self.session.add(CategoryOverride(name_normalized=name_normalized, category_id=category_id))
        if apply_existing:
            items = await self.session.scalars(select(Item).where(Item.name_normalized == name_normalized))
            for it in items:
                it.category_id = category_id
