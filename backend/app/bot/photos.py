"""Receipt photos and files: pictures, PDF receipts (a PDF statement goes to the statement flow)."""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from app.bank import looks_like_statement, statement_text
from app.bot.common import download, edit, get_sender, llm_slots, send_alerts
from app.bot.statements import read_statement
from app.bot.ui import duplicate_keyboard, format_receipt, receipt_keyboard
from app.db.session import session_factory
from app.receipts.service import ProcessResult, ReceiptService, split_who
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)
router = Router()


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot):
    if message.photo:
        await handle_image(message, bot, message.photo[-1].file_id, "jpg")


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_document(message: Message, bot: Bot):
    if message.document is None:
        return
    ext = (message.document.mime_type or "image/jpeg").split("/")[-1].replace("jpeg", "jpg")
    await handle_image(message, bot, message.document.file_id, ext)


@router.message(F.document.mime_type == "application/pdf")
async def on_pdf(message: Message, bot: Bot):
    if message.document is None:
        return
    data = await download(bot, message.document.file_id)
    try:
        text = await asyncio.to_thread(statement_text, data, "x.pdf")
    except Exception:
        text = ""  # a scan: read it as a receipt picture
    if looks_like_statement(text):
        await read_statement(message, text)
        return
    await handle_image(message, bot, message.document.file_id, "pdf", data=data)


async def handle_image(message: Message, bot: Bot, file_id: str, ext: str, data: bytes | None = None):
    status = await message.reply("⏳ Распознаю чек…")
    try:
        if data is None:
            data = await download(bot, file_id)
        async with llm_slots, session_factory()() as session:
            svc = ReceiptService(session)
            sender = await get_sender(svc, message)
            # caption "Маша: тетради" books the receipt for Маша with description "тетради"
            caption = (message.caption or "").strip()
            owner, note = sender, caption
            who, rest = split_who(caption)
            if who:
                found = await svc.find_user(who)
                if found:
                    owner, note = found, rest
            if ext == "pdf":
                res: ProcessResult = await svc.process_pdf(
                    data, owner, chat_id=message.chat.id, message_id=message.message_id, note=note or None
                )
            else:
                res = await svc.process_photo(
                    data,
                    owner,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    ext=ext,
                    note=note or None,
                )
            if res.duplicate_of:
                d = res.duplicate_of
                when = f" от {d.purchased_at:%d.%m.%Y}" if d.purchased_at else ""
                await edit(status, f"♻️ Этот чек уже записан{when}.", receipt_keyboard(d.id))
                return
            if res.not_receipt:
                await edit(
                    status,
                    "🤔 Не похоже на чек, ничего не записал. "
                    "Выписку из банка присылайте PDF-файлом или загрузите в вебе.",
                )
                return
            receipt = res.receipt
            if receipt is None:
                await edit(status, "❌ Не удалось записать чек.")
                return
            receipt.bot_message_id = status.message_id
            await session.commit()
            if res.error:
                await edit(
                    status,
                    "❌ Не удалось распознать: нейросеть недоступна.\n"
                    "Фото сохранено, распознавание можно повторить в вебе.",
                    receipt_keyboard(receipt.id),
                )
                return
            text = await format_receipt(session, receipt, sender.id if sender else None)
            if d := res.maybe_duplicate_of:
                when = f" от {d.purchased_at:%d.%m.%Y %H:%M}" if d.purchased_at else ""
                text += f"\n\n❓ <b>Не дубль ли это?</b> Такой же чек из того же магазина уже записан{when} (№{d.id})."
                await edit(status, text, duplicate_keyboard(receipt.id, d.id))
                return
            await edit(status, text, receipt_keyboard(receipt.id))
            await send_alerts(bot, message.chat.id, await new_budget_alerts(session, receipt))
    except Exception:
        log.exception("failed to process receipt")
        await edit(status, "❌ Что-то пошло не так при обработке чека.")
