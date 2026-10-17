import asyncio
import io
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Category, CategoryOverride, Item, Receipt, User
from app.llm.client import LLMClient, LLMError
from app.llm.prompt import manual_system, receipt_system
from app.llm.schema import ParsedReceipt
from app.receipts.money import round2
from app.receipts.qr import FiscalQR, find_fiscal_qr, parse_fiscal_qr
from app.receipts.text import CategoryMatcher, normalize_name

log = logging.getLogger(__name__)
register_heif_opener()


@dataclass
class ProcessResult:
    receipt: Receipt | None = None
    duplicate_of: Receipt | None = None
    not_receipt: bool = False
    error: str | None = None


@dataclass
class Checks:
    reasons: list[str] = field(default_factory=list)

    def add(self, msg: str):
        self.reasons.append(msg)


def now_local() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(get_settings().timezone)).replace(tzinfo=None, microsecond=0)


NO_DESCRIPTION = "Без описания"

_MANUAL_RE = re.compile(
    r"^(?:(?P<name>.+?)\s+)?(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|евро)?\s*$",
    re.IGNORECASE,
)
_WHO_RE = re.compile(r"^(?P<who>@\w{3,32}|[^\s:@]{2,30}):\s*(?P<rest>.*)$", re.S)


def parse_manual_text(text: str) -> tuple[str | None, float] | None:
    """'такси 12' -> ('Такси', 12.0); '12,50' -> (None, 12.5). Amounts are in EUR."""
    m = _MANUAL_RE.match(text.strip())
    if not m:
        return None
    name = m["name"].strip().capitalize() if m["name"] else None
    return name, float(m["amount"].replace(",", "."))


def split_who(text: str) -> tuple[str | None, str]:
    """'Маша: кино 12' -> ('Маша', 'кино 12'); '@masha: 12' -> ('@masha', '12')."""
    m = _WHO_RE.match((text or "").strip())
    if not m:
        return None, (text or "").strip()
    return m["who"], m["rest"].strip()


class ReceiptService:
    def __init__(self, session: AsyncSession, llm: LLMClient | None = None):
        self.session = session
        self.llm = llm or LLMClient()
        self.settings = get_settings()

    # ---------- helpers ----------

    async def get_or_create_user(
        self, telegram_id: int, name: str, username: str | None = None
    ) -> User:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, name=name, username=username)
            self.session.add(user)
            await self.session.flush()
        elif user.name != name or user.username != username:
            user.name, user.username = name, username
        return user

    async def find_user(self, token: str) -> User | None:
        """Family member by @username or by name (full or first word), case-insensitive."""
        users = list(await self.session.scalars(select(User)))
        t = token.strip()
        if t.startswith("@"):
            uname = t[1:].lower()
            return next((u for u in users if (u.username or "").lower() == uname), None)
        key = normalize_name(t)
        for u in users:
            full = normalize_name(u.name)
            if key == full or key == full.split(" ")[0]:
                return u
        return None

    async def matcher(self) -> CategoryMatcher:
        cats = list(await self.session.scalars(select(Category)))
        return CategoryMatcher(cats)

    async def overrides(self, names: set[str]) -> dict[str, int]:
        if not names:
            return {}
        rows = await self.session.scalars(
            select(CategoryOverride).where(CategoryOverride.name_normalized.in_(names))
        )
        return {r.name_normalized: r.category_id for r in rows}

    def _save_image(self, data: bytes, ext: str = "jpg") -> str:
        now = now_local()
        rel = Path("receipts") / f"{now:%Y}" / f"{now:%m}" / f"{uuid.uuid4().hex}.{ext}"
        path = self.settings.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel.as_posix()

    def image_abspath(self, receipt: Receipt) -> Path | None:
        if not receipt.image_path:
            return None
        return self.settings.data_dir / receipt.image_path

    async def delete_receipt(self, receipt: Receipt) -> None:
        path = self.image_abspath(receipt)
        await self.session.delete(receipt)
        await self.session.commit()
        if path and path.exists():
            path.unlink()

    # ---------- photo receipts ----------

    async def process_photo(
        self,
        data: bytes,
        user: User | None,
        chat_id: int | None = None,
        message_id: int | None = None,
        ext: str = "jpg",
        note: str | None = None,
    ) -> ProcessResult:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image.load()
        qr, qr_raw, rotation = await asyncio.to_thread(find_fiscal_qr, image)
        if rotation:
            # receipt shot sideways or upside down: straighten it for the model and for viewing
            image = image.rotate(rotation, expand=True)
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=92)
            data, ext = buf.getvalue(), "jpg"

        if qr:
            dup = await self.session.scalar(
                select(Receipt).where(Receipt.fiscal_key == qr.fiscal_key)
            )
            if dup:
                return ProcessResult(duplicate_of=dup)

        receipt = Receipt(
            source="photo",
            status="pending",
            user_id=user.id if user else None,
            image_path=self._save_image(data, ext),
            qr_raw=qr_raw,
            fiscal_key=qr.fiscal_key if qr else None,
            purchased_at=qr.purchased_at if qr else None,
            total=qr.amount if qr else None,
            chat_id=chat_id,
            message_id=message_id,
            note=note or None,
            items=[],
        )
        self.session.add(receipt)
        await self.session.commit()

        result = await self.recognize(receipt, image, qr)
        return result

    async def reprocess(self, receipt: Receipt, models: list[str] | None = None) -> ProcessResult:
        path = self.image_abspath(receipt)
        if not path or not path.exists():
            return ProcessResult(receipt=receipt, error="У записи нет фото чека")
        image = ImageOps.exif_transpose(Image.open(path))
        image.load()
        qr = parse_fiscal_qr(receipt.qr_raw) if receipt.qr_raw else None
        return await self.recognize(receipt, image, qr, models=models, keep_if_not_receipt=True)

    async def recognize(
        self,
        receipt: Receipt,
        image: Image.Image,
        qr: FiscalQR | None,
        models: list[str] | None = None,
        keep_if_not_receipt: bool = False,
    ) -> ProcessResult:
        matcher = await self.matcher()
        try:
            res = await self.llm.parse_receipt(
                image, receipt_system(matcher.path_list()), models, hint=receipt.note
            )
        except LLMError as e:
            receipt.status = "failed"
            receipt.review_reason = f"Нейросеть не ответила: {e}"[:2000]
            await self.session.commit()
            return ProcessResult(receipt=receipt, error=str(e))

        parsed = res.data
        if not parsed.is_receipt and not qr:
            if keep_if_not_receipt:
                receipt.status = "needs_review"
                receipt.review_reason = "Нейросеть не распознала чек на фото"
                await self.session.commit()
                return ProcessResult(receipt=receipt, not_receipt=True)
            await self.delete_receipt(receipt)
            return ProcessResult(not_receipt=True)

        receipt.llm_model = res.model
        receipt.raw_llm_json = res.raw
        await self.apply_parsed(receipt, parsed, matcher, qr)
        await self.session.commit()
        return ProcessResult(receipt=receipt)

    async def apply_parsed(
        self,
        receipt: Receipt,
        parsed: ParsedReceipt,
        matcher: CategoryMatcher,
        qr: FiscalQR | None,
    ) -> None:
        checks = Checks()
        tol = self.settings.review_tolerance

        receipt.store = (parsed.store or receipt.store or "").strip() or None

        # The QR code is the most reliable source for date and total.
        receipt.purchased_at = (
            (qr.purchased_at if qr else None) or parsed.purchased_at or receipt.purchased_at or now_local()
        )
        total = parsed.total
        if qr:
            if total is not None and abs(total - qr.amount) > tol:
                checks.add(f"Сумма в QR ({qr.amount:.2f}) не совпадает с итогом чека ({total:.2f})")
            total = qr.amount
        receipt.total = round2(total)

        # Rebuild items
        items = await receipt.awaitable_attrs.items
        items.clear()
        await self.session.flush()
        names = {normalize_name(i.name_original) for i in parsed.items}
        remembered = await self.overrides(names)
        for pos, pi in enumerate(parsed.items):
            norm = normalize_name(pi.name_original)
            cat_id = remembered.get(norm)
            if cat_id is None:
                cat = matcher.match(pi.category)
                cat_id = cat.id if cat else None
            unit = pi.unit_price
            if unit is None and pi.qty:
                unit = pi.total / pi.qty
            receipt.items.append(
                Item(
                    position=pos,
                    name_original=pi.name_original.strip(),
                    name_ru=(pi.name_ru or "").strip() or None,
                    name_normalized=norm,
                    qty=pi.qty,
                    unit_price=round2(unit),
                    total=round2(pi.total),
                    category_id=cat_id,
                )
            )

        if not parsed.items and receipt.total is not None:
            # e.g. a greengrocer's receipt with only the total: book it as one line
            name = receipt.note or receipt.store or "Покупка"
            remembered = await self.overrides({normalize_name(name)})
            receipt.items.append(
                Item(
                    position=0,
                    name_original=name,
                    name_ru=name,
                    name_normalized=normalize_name(name),
                    qty=1,
                    unit_price=receipt.total,
                    total=receipt.total,
                    category_id=remembered.get(normalize_name(name)),
                )
            )
        elif not parsed.items:
            checks.add("Не найдено ни одной позиции")
        elif receipt.total is not None:
            items_sum = sum(i.total for i in parsed.items)
            if abs(items_sum - receipt.total) > tol:
                checks.add(
                    f"Сумма позиций ({items_sum:.2f}) не совпадает с итогом ({receipt.total:.2f})"
                )
        if receipt.total is None:
            receipt.total = round2(sum(i.total for i in parsed.items))
            checks.add("Итог чека не найден, посчитан по позициям")

        receipt.status = "needs_review" if checks.reasons else "ok"
        receipt.review_reason = "\n".join(checks.reasons) or None

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
    ) -> Receipt:
        receipt = Receipt(
            source=source,
            status="ok",
            user_id=user_id,
            store=store,
            purchased_at=purchased_at or now_local(),
            total=round2(amount),
            note=note,
            chat_id=chat_id,
            message_id=message_id,
        )
        receipt.items.append(
            Item(
                position=0,
                name_original=name,
                name_ru=name,
                name_normalized=normalize_name(name),
                qty=1,
                unit_price=round2(amount),
                total=round2(amount),
                category_id=category_id,
            )
        )
        self.session.add(receipt)
        await self.session.commit()
        return receipt

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
        category = None
        if quick:
            name, amount = quick
            remembered = await self.overrides({normalize_name(name)})
            if remembered:
                category = await self.session.get(Category, remembered[normalize_name(name)])
        if category is None:
            try:
                res = await self.llm.parse_manual(text, manual_system(matcher.path_list()))
                if name is None:
                    name, amount = res.data.name, res.data.amount
                category = matcher.match(res.data.category)
            except LLMError as e:
                log.warning("manual entry LLM failed: %s", e)
                category = matcher.fallback
        if not name or amount is None:
            return None
        return await self.book_single(
            name=name,
            amount=amount,
            category_id=category.id if category else None,
            user_id=user.id if user else None,
            source="manual",
            chat_id=chat_id,
            message_id=message_id,
        )

    async def classify(self, name: str, amount: float) -> int | None:
        """Category for a single free-text purchase: remembered choice first, then the LLM."""
        remembered = await self.overrides({normalize_name(name)})
        if remembered:
            return remembered[normalize_name(name)]
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
        items = await receipt.awaitable_attrs.items
        if text and len(items) == 1 and (
            items[0].category_id is None or items[0].name_original in {NO_DESCRIPTION, "Покупка", receipt.store}
        ):
            it = items[0]
            it.name_original = it.name_ru = text[:300]
            it.name_normalized = normalize_name(text)
            it.category_id = await self.classify(text, it.total) or it.category_id
        await self.session.commit()
        return receipt

    # ---------- edits from the web ----------

    async def remember_category(self, name_normalized: str, category_id: int, apply_existing: bool):
        ov = await self.session.scalar(
            select(CategoryOverride).where(CategoryOverride.name_normalized == name_normalized)
        )
        if ov:
            ov.category_id = category_id
        else:
            self.session.add(
                CategoryOverride(name_normalized=name_normalized, category_id=category_id)
            )
        if apply_existing:
            items = await self.session.scalars(
                select(Item).where(Item.name_normalized == name_normalized)
            )
            for it in items:
                it.category_id = category_id
