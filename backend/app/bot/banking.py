"""Bank notifications forwarded to the group, and `/bank`."""

import html
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.bank import handle_bank_text, looks_like_bank_message
from app.bot.common import get_sender, reply_with_record
from app.bot.ui import money, receipt_keyboard
from app.db.session import session_factory
from app.i18n import t
from app.llm.client import LLMError
from app.receipts.service import ReceiptService

log = logging.getLogger(__name__)
router = Router()


async def _bank(message: Message, bot: Bot, text: str, explicit: bool):
    async with session_factory()() as session:
        svc = ReceiptService(session)
        sender = await get_sender(svc, message)
        try:
            results = await handle_bank_text(svc, text, sender, chat_id=message.chat.id, message_id=message.message_id)
        except LLMError as e:
            log.warning("bank message failed: %s", e)
            if explicit:
                await message.reply(t("bot.llm_down_later"))
            return
        if not results:
            if explicit:
                await message.reply(t("bot.bank_nothing"))
            return
        for r in results:
            if r.match:
                m = r.match
                when = t("bot.bank_from", date=f"{m.purchased_at:%d.%m}") if m.purchased_at else ""
                what = {"income": t("bot.bank_income"), "transfer": t("bot.bank_transfer")}.get(r.kind, t("bot.bank_debit"))
                where = f" ({html.escape(r.tx.merchant)})" if r.tx.merchant else ""
                await message.reply(
                    t("bot.bank_already", what=what, amount=money(r.tx.amount), where=where, when=when),
                    reply_markup=receipt_keyboard(m.id),
                )
                continue
            if r.receipt:
                await reply_with_record(message, bot, session, r.receipt, sender, prefix="🏦 ")


@router.message(Command("bank"))
async def on_bank_command(message: Message, bot: Bot, command: CommandObject):
    text = (command.args or "").strip()
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    if not text:
        await message.reply(t("bot.bank_format"))
        return
    await _bank(message, bot, text, explicit=True)


@router.message(F.text.func(looks_like_bank_message))
async def on_bank_text(message: Message, bot: Bot):
    await _bank(message, bot, message.text or "", explicit=False)
