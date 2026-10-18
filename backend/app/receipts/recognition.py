"""Recognition of receipts: photos, PDFs, e-mails, the model cascade, duplicates."""

import asyncio
import logging
from datetime import timedelta

from PIL import Image, ImageOps
from sqlalchemy import select

from app.clock import now_local
from app.constants import Kind, purchase_default
from app.db.models import Item, Receipt, User
from app.i18n import t
from app.llm.client import LLMError
from app.llm.prompt import receipt_system
from app.llm.schema import ParsedReceipt
from app.receipts.base import ProcessResult, ServiceBase, single_item
from app.receipts.images import pdf_text_and_preview, prepare_photo
from app.receipts.money import round2
from app.receipts.parsing import add_months
from app.receipts.qr import FiscalQR, parse_fiscal_qr
from app.receipts.text import CategoryMatcher, normalize_name

log = logging.getLogger(__name__)

DUPLICATE_MINUTES = 30  # the same total and shop within this time is the same purchase
PROBABLE_DUPLICATE_DAYS = 2  # the same shop, total and lines this close: ask whether it is a repeat
DUPLICATE_NEAR_MINUTES = 10  # the same total this close in time is the same purchase whatever the shop is called


class RecognitionMixin(ServiceBase):
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
            return ProcessResult(receipt=receipt, error=t("recognition.no_photo"))

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
            assert image is not None, "a receipt is read from a picture or from text"
            return await self.llm.parse_receipt(image, system, ms, hint=receipt.note)

        try:
            res = await read(models)
        except LLMError as e:
            receipt.status = "failed"
            receipt.review_reason = t("recognition.llm_down", error=e)[:2000]
            await self.session.commit()
            return ProcessResult(receipt=receipt, error=str(e))

        parsed = res.data
        if not parsed.is_receipt and not qr:
            if keep_if_not_receipt:
                receipt.status = "needs_review"
                receipt.review_reason = t("recognition.llm_failed")
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
                        receipt.review_reason += t("recognition.reread", model=res2.model)

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
            if r.purchased_at is None:
                continue
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
        when = (qr.purchased_at if qr else None) or parsed.purchased_at or receipt.purchased_at or now_local()
        receipt.purchased_at = when
        if when > now_local() + timedelta(minutes=10):
            reasons.append(t("recognition.future_date", when=f"{when:%d.%m.%Y %H:%M}"))
        total = parsed.total
        if qr:
            if total is not None and abs(total - qr.amount) > tol:
                reasons.append(t("recognition.qr_mismatch", qr=f"{qr.amount:.2f}", total=f"{total:.2f}"))
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
            name = receipt.note or receipt.store or purchase_default()
            receipt.items.append(single_item(name, receipt.total, await self.override_category(name)))
        elif not parsed.items:
            reasons.append(t("recognition.no_items"))
        elif (receipt_total := receipt.total) is not None:
            items_sum = sum(i.total for i in parsed.items)
            if abs(items_sum - receipt_total) > tol:
                reasons.append(t("recognition.sum_mismatch", items=f"{items_sum:.2f}", total=f"{receipt_total:.2f}"))
        if receipt.total is None:
            receipt.total = round2(sum(i.total for i in parsed.items))
            reasons.append(t("recognition.total_computed"))

        receipt.status = "needs_review" if reasons else "ok"
        receipt.review_reason = "\n".join(reasons) or None
