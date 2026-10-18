import asyncio
import calendar
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_local
from app.config import get_settings
from app.constants import INCOME_DEFAULT, NO_DESCRIPTION, PURCHASE_DEFAULT, Kind
from app.db.models import Category, CategoryOverride, Item, Receipt, User
from app.family import apply_family_names, find_user
from app.llm.client import LLMClient, LLMError, get_llm
from app.llm.prompt import manual_system, receipt_system
from app.llm.schema import ParsedReceipt
from app.receipts.money import round2
from app.receipts.qr import FiscalQR, find_fiscal_qr, parse_fiscal_qr
from app.receipts.text import CategoryMatcher, csv_list, normalize_name

log = logging.getLogger(__name__)

DUPLICATE_MINUTES = 30  # the same total and shop within this time is the same purchase
PROBABLE_DUPLICATE_DAYS = 2  # the same shop, total and lines this close: ask whether it is a repeat
DUPLICATE_NEAR_MINUTES = 10  # the same total this close in time is the same purchase whatever the shop is called
register_heif_opener()


@dataclass
class ProcessResult:
    receipt: Receipt | None = None
    duplicate_of: Receipt | None = None
    # saved, but looks like a record that is already there: the person is asked
    maybe_duplicate_of: Receipt | None = None
    not_receipt: bool = False
    error: str | None = None


def single_item(name: str, total: float | None, category_id: int | None, position: int = 0) -> Item:
    """The only line of a one-line record: a manual entry, a bank operation, a total-only receipt."""
    return Item(
        position=position,
        name_original=name,
        name_ru=name,
        name_normalized=normalize_name(name),
        qty=1,
        unit_price=round2(total),
        total=round2(total),
        category_id=category_id,
    )


_MANUAL_RE = re.compile(
    r"^(?:(?P<name>.+?)\s+)?(?P<amount>\d+(?:[.,]\d{1,2})?)\s*(?:€|eur|евро)?\s*$",
    re.IGNORECASE,
)
_WHO_RE = re.compile(r"^(?P<who>@\w{3,32}|[^\s:@]{2,30}):\s*(?P<rest>.*)$", re.DOTALL)


def parse_manual_text(text: str) -> tuple[str | None, float] | None:
    """'такси 12' -> ('Такси', 12.0); '12,50' -> (None, 12.5). Amounts are in EUR."""
    m = _MANUAL_RE.match(text.strip())
    if not m:
        return None
    name = m["name"].strip().capitalize() if m["name"] else None
    return name, float(m["amount"].replace(",", "."))


_INCOME_RULES = [
    (re.compile(r"зарплат|заплата|аванс|salary|payroll|wage", re.IGNORECASE), "Зарплата"),
    (re.compile(r"возврат|refund|return|възстановен|върнат", re.IGNORECASE), "Возвраты"),
    (re.compile(r"кэшбэк|кешбэк|кешбек|cashback|cash back|процент|лихв|interest", re.IGNORECASE), "Проценты и кэшбэк"),
    (re.compile(r"подработ|фриланс|freelance|гонорар|хонорар", re.IGNORECASE), "Подработка"),
    (re.compile(r"подар|помощ|gift", re.IGNORECASE), "Подарки и помощь"),
]


def income_category_name(name: str) -> str:
    """Income category by keywords; there are few incomes, an LLM call is not worth it."""
    for rx, cat in _INCOME_RULES:
        if rx.search(name or ""):
            return cat
    from app.db.seed import INCOME_OTHER

    return INCOME_OTHER


def split_who(text: str) -> tuple[str | None, str]:
    """'Маша: кино 12' -> ('Маша', 'кино 12'); '@masha: 12' -> ('@masha', '12')."""
    m = _WHO_RE.match((text or "").strip())
    if not m:
        return None, (text or "").strip()
    return m["who"], m["rest"].strip()


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def prepare_photo(data: bytes, ext: str) -> tuple[Image.Image, FiscalQR | None, str | None, bytes, str]:
    """Decodes a photo, reads its fiscal QR code and straightens a receipt shot sideways or
    upside down. CPU work: call it in a thread. Returns (image, qr, qr text, bytes to keep, ext)."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image.load()
    qr, qr_raw, rotation = find_fiscal_qr(image)
    if rotation:
        image = image.rotate(rotation, expand=True)
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=92)
        data, ext = buf.getvalue(), "jpg"
    return image, qr, qr_raw, data, ext


def pdf_text_and_preview(data: bytes, max_pages: int = 3) -> tuple[str, bytes]:
    """Text layer of the first pages and a JPEG of the first page."""
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    except Exception:
        text = ""
    pdf = pdfium.PdfDocument(data)
    page = pdf[0].render(scale=2.5).to_pil().convert("RGB")
    buf = io.BytesIO()
    page.save(buf, format="JPEG", quality=90)
    return text, buf.getvalue()


class ReceiptService:
    def __init__(self, session: AsyncSession, llm: LLMClient | None = None, auto_products: bool = True):
        self.session = session
        self.llm = llm or get_llm()
        self.auto_products = auto_products
        self.settings = get_settings()

    # ---------- helpers ----------

    async def get_or_create_user(self, telegram_id: int, name: str, username: str | None = None) -> User:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, name=name, username=username)
            self.session.add(user)
            await self.session.flush()
        elif user.username != username:
            # the name is kept: it may have been changed by hand in Settings → Family
            user.username = username
        return user

    async def find_user(self, token: str) -> User | None:
        return await find_user(self.session, token)

    async def matcher(self) -> CategoryMatcher:
        cats = list(await self.session.scalars(select(Category).where(Category.kind == Kind.EXPENSE)))
        return CategoryMatcher(cats)

    async def income_category(self, name: str) -> int | None:
        target = income_category_name(name)
        return await self.session.scalar(
            select(Category.id).where(Category.kind == Kind.INCOME, Category.name == target)
        )

    async def override_category(self, name: str) -> int | None:
        """The category a person once chose for this product name, if any."""
        key = normalize_name(name)
        return (await self.overrides({key})).get(key)

    async def overrides(self, names: set[str]) -> dict[str, int]:
        if not names:
            return {}
        rows = await self.session.scalars(select(CategoryOverride).where(CategoryOverride.name_normalized.in_(names)))
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
        source: str = "photo",
        external_id: str | None = None,
    ) -> ProcessResult:
        if dup := await self._duplicate_external(external_id):
            return ProcessResult(duplicate_of=dup)
        image, qr, qr_raw, data, ext = await asyncio.to_thread(prepare_photo, data, ext)

        if qr:
            dup = await self.session.scalar(select(Receipt).where(Receipt.fiscal_key == qr.fiscal_key))
            if dup:
                return ProcessResult(duplicate_of=dup)

        receipt = Receipt(
            source=source,
            external_id=external_id,
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

    async def _duplicate_external(self, external_id: str | None) -> Receipt | None:
        if not external_id:
            return None
        return await self.session.scalar(select(Receipt).where(Receipt.external_id == external_id))

    async def process_text_receipt(
        self,
        text: str,
        user: User | None,
        *,
        source: str = "email",
        external_id: str | None = None,
        note: str | None = None,
        image_data: bytes | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> ProcessResult:
        """An electronic receipt as text (e-mail body, PDF with a text layer)."""
        if dup := await self._duplicate_external(external_id):
            return ProcessResult(duplicate_of=dup)
        receipt = Receipt(
            source=source,
            external_id=external_id,
            status="pending",
            user_id=user.id if user else None,
            image_path=self._save_image(image_data, "jpg") if image_data else None,
            source_text=text[:50000],
            note=note or None,
            chat_id=chat_id,
            message_id=message_id,
            items=[],
        )
        self.session.add(receipt)
        await self.session.commit()
        return await self.recognize(receipt, None, None, text=text)

    async def process_pdf(
        self,
        data: bytes,
        user: User | None,
        *,
        source: str = "photo",
        external_id: str | None = None,
        note: str | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
    ) -> ProcessResult:
        """PDF receipt: its text layer is read when present, otherwise the rendered first page.
        The first page is kept as the receipt picture either way."""
        text, preview = await asyncio.to_thread(pdf_text_and_preview, data)
        if len(text.strip()) > 30:
            return await self.process_text_receipt(
                text,
                user,
                source=source,
                external_id=external_id,
                note=note,
                image_data=preview,
                chat_id=chat_id,
                message_id=message_id,
            )
        return await self.process_photo(
            preview,
            user,
            chat_id=chat_id,
            message_id=message_id,
            note=note,
            source=source,
            external_id=external_id,
        )

    async def reprocess(self, receipt: Receipt, models: list[str] | None = None) -> ProcessResult:
        if receipt.source_text:
            return await self.recognize(
                receipt, None, None, models=models, keep_if_not_receipt=True, text=receipt.source_text
            )
        path = self.image_abspath(receipt)
        if not path or not path.exists():
            return ProcessResult(receipt=receipt, error="У записи нет фото чека")

        def load() -> Image.Image:
            img = ImageOps.exif_transpose(Image.open(path))
            img.load()
            return img

        image = await asyncio.to_thread(load)
        qr = parse_fiscal_qr(receipt.qr_raw) if receipt.qr_raw else None
        return await self.recognize(receipt, image, qr, models=models, keep_if_not_receipt=True)

    async def recognize(
        self,
        receipt: Receipt,
        image: Image.Image | None,
        qr: FiscalQR | None,
        models: list[str] | None = None,
        keep_if_not_receipt: bool = False,
        text: str | None = None,
    ) -> ProcessResult:
        """Reads the receipt from a photo (image) or from e-mail text (text) and fills it in.
        If the sums do not add up, the receipt is re-read once by LLM_STRONG_MODELS."""
        matcher = await self.matcher()
        system = receipt_system(matcher.path_list())

        async def read(ms: list[str] | None):
            if text is not None:
                return await self.llm.parse_receipt_text(text, system, hint=receipt.note, models=ms)
            return await self.llm.parse_receipt(image, system, ms, hint=receipt.note)

        try:
            res = await read(models)
        except LLMError as e:
            receipt.status = "failed"
            receipt.review_reason = f"Нейросеть не ответила: {e}"[:2000]
            await self.session.commit()
            return ProcessResult(receipt=receipt, error=str(e))

        parsed = res.data
        if not parsed.is_receipt and not qr:
            if keep_if_not_receipt:
                receipt.status = "needs_review"
                receipt.review_reason = "Нейросеть не распознала чек"
                await self.session.commit()
                return ProcessResult(receipt=receipt, not_receipt=True)
            await self.delete_receipt(receipt)
            return ProcessResult(not_receipt=True)

        receipt.llm_model = res.model
        receipt.raw_llm_json = res.raw
        await self.apply_parsed(receipt, parsed, matcher, qr)

        strong = [m for m in self.settings.strong_models if m != res.model]
        if receipt.status == "needs_review" and models is None and strong:
            # apply_parsed flushed: commit now, or SQLite keeps the write lock for the whole
            # second request and the usage log (own connection) cannot be written
            await self.session.commit()
            try:
                res2 = await read(strong)
            except LLMError as e:
                log.warning("strong models failed: %s", e)
            else:
                if res2.data.is_receipt or qr:
                    receipt.llm_model = res2.model
                    receipt.raw_llm_json = res2.raw
                    await self.apply_parsed(receipt, res2.data, matcher, qr)
                    if receipt.review_reason:
                        receipt.review_reason += f"\n(перечитано моделью {res2.model})"

        if not keep_if_not_receipt and (dup := await self.find_duplicate(receipt)):
            await self.delete_receipt(receipt)
            return ProcessResult(duplicate_of=dup)
        maybe = None if keep_if_not_receipt else await self.find_probable_duplicate(receipt)
        await self.session.commit()
        self.after_items_changed(receipt)
        return ProcessResult(receipt=receipt, maybe_duplicate_of=maybe)

    async def find_probable_duplicate(self, receipt: Receipt) -> Receipt | None:
        """Not sure enough to drop it: the same shop, total and number of lines within a couple of
        days (the time on a picture is often misread). The person decides."""
        if receipt.total is None or receipt.purchased_at is None or not receipt.store or not receipt.items:
            return None
        at, window = receipt.purchased_at, timedelta(days=PROBABLE_DUPLICATE_DAYS)
        shop = normalize_name(receipt.store)
        candidates = await self.session.scalars(
            select(Receipt)
            .where(
                Receipt.id != receipt.id,
                Receipt.kind == Kind.EXPENSE,
                Receipt.source.in_(("photo", "email")),
                Receipt.status != "failed",
                Receipt.total.between(receipt.total - 0.01, receipt.total + 0.01),
                Receipt.purchased_at.between(at - window, at + window),
            )
            .order_by(Receipt.id)
        )
        for r in candidates:
            if normalize_name(r.store or "") == shop and len(r.items) == len(receipt.items):
                return r
        return None

    async def find_duplicate(self, receipt: Receipt) -> Receipt | None:
        """The same purchase recorded before from another picture of it: a photo and a screenshot
        from the shop's app (no QR code) are different files with the same total and time.
        Same total within DUPLICATE_MINUTES, and the same shop, or nearly the same minute."""
        if receipt.total is None or receipt.purchased_at is None or receipt.kind != Kind.EXPENSE:
            return None
        at, window = receipt.purchased_at, timedelta(minutes=DUPLICATE_MINUTES)
        candidates = await self.session.scalars(
            select(Receipt)
            .where(
                Receipt.id != receipt.id,
                Receipt.kind == Kind.EXPENSE,
                Receipt.source.in_(("photo", "email")),
                Receipt.status != "failed",
                Receipt.total.between(receipt.total - 0.01, receipt.total + 0.01),
                Receipt.purchased_at.between(at - window, at + window),
            )
            .order_by(Receipt.id)
        )
        shop = normalize_name(receipt.store or "")
        for r in candidates:
            close = abs(r.purchased_at - at) <= timedelta(minutes=DUPLICATE_NEAR_MINUTES)
            if close or not shop or not r.store or normalize_name(r.store) == shop:
                return r
        return None

    def after_items_changed(self, receipt: Receipt) -> None:
        """Groups new product names in the background, so the bot answers without waiting."""
        if not self.auto_products:
            return
        from app.products import schedule_grouping

        schedule_grouping([i.name_normalized for i in receipt.items if i.total > 0], self.llm)

    async def apply_parsed(
        self,
        receipt: Receipt,
        parsed: ParsedReceipt,
        matcher: CategoryMatcher,
        qr: FiscalQR | None,
    ) -> None:
        reasons: list[str] = []
        tol = self.settings.review_tolerance

        receipt.store = (parsed.store or receipt.store or "").strip() or None

        # The QR code is the most reliable source for date and total.
        receipt.purchased_at = (
            (qr.purchased_at if qr else None) or parsed.purchased_at or receipt.purchased_at or now_local()
        )
        if receipt.purchased_at > now_local() + timedelta(minutes=10):
            reasons.append(f"Дата чека в будущем ({receipt.purchased_at:%d.%m.%Y %H:%M}), проверьте дату и время")
        total = parsed.total
        if qr:
            if total is not None and abs(total - qr.amount) > tol:
                reasons.append(f"Сумма в QR ({qr.amount:.2f}) не совпадает с итогом чека ({total:.2f})")
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
                    warranty_until=add_months(receipt.purchased_at.date(), pi.warranty_months)
                    if pi.warranty_months
                    else None,
                )
            )

        if not parsed.items and receipt.total is not None:
            # e.g. a greengrocer's receipt with only the total: book it as one line
            name = receipt.note or receipt.store or PURCHASE_DEFAULT
            receipt.items.append(single_item(name, receipt.total, await self.override_category(name)))
        elif not parsed.items:
            reasons.append("Не найдено ни одной позиции")
        elif receipt.total is not None:
            items_sum = sum(i.total for i in parsed.items)
            if abs(items_sum - receipt.total) > tol:
                reasons.append(f"Сумма позиций ({items_sum:.2f}) не совпадает с итогом ({receipt.total:.2f})")
        if receipt.total is None:
            receipt.total = round2(sum(i.total for i in parsed.items))
            reasons.append("Итог чека не найден, посчитан по позициям")

        receipt.status = "needs_review" if reasons else "ok"
        receipt.review_reason = "\n".join(reasons) or None

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
        kind: Kind = Kind.EXPENSE,
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
            category_id = await self.override_category(name)
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
        dropped, an income gets an income category."""
        receipt.kind = kind
        receipt.peer_user_id = peer.id if kind == Kind.TRANSFER and peer else None
        cat_kind = {c.id: c.kind for c in await self.session.scalars(select(Category))}
        for it in await receipt.awaitable_attrs.items:
            if kind == Kind.TRANSFER or (it.category_id and cat_kind.get(it.category_id) != kind):
                it.category_id = None
            if kind == Kind.INCOME and it.category_id is None:
                it.category_id = await self.income_category(it.name_original)
        await self.session.commit()

    async def remember_bank_name(self, member: User, name: str) -> int:
        """Transfers to/from this name are inside the family from now on, recorded ones too."""
        names = csv_list(member.bank_names)
        if normalize_name(name) not in {normalize_name(n) for n in names}:
            member.bank_names = ",".join([*names, name.strip()])
            await self.session.commit()
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
