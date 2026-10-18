"""Helpers shared by the bot's handlers."""

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, ReactionTypeEmoji
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.ui import format_receipt, receipt_keyboard
from app.db.models import Receipt, User
from app.i18n import t
from app.receipts.service import ReceiptService
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)

# free LLM tiers are rate limited: do not hammer them when someone sends an album
llm_slots = asyncio.Semaphore(2)


def callback_message(cb: CallbackQuery) -> Message | None:
    """The message a button is under; None when Telegram no longer has it."""
    return cb.message if isinstance(cb.message, Message) else None


def callback_arg(cb: CallbackQuery) -> str:
    """'del:12' -> '12'."""
    return (cb.data or "").split(":", 1)[-1]


async def download(bot: Bot, file_id: str) -> bytes:
    file = await bot.download(file_id)
    if file is None:
        raise RuntimeError("Telegram returned no file")
    return file.read()


async def edit(msg: Message, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        # e.g. Telegram rejects a URL button: retry without the keyboard
        log.warning("edit failed (%s), retrying without keyboard", e)
        await msg.edit_text(text)


async def send_alerts(bot: Bot, chat_id: int, alerts: list[str]):
    for a in alerts:
        await bot.send_message(chat_id, a)


async def get_sender(svc: ReceiptService, message: Message) -> User | None:
    u = message.from_user
    if not u:
        return None
    user = await svc.get_or_create_user(u.id, u.full_name, u.username)
    await svc.session.commit()
    return user


def unknown_member(who: str) -> str:
    return t("bot.unknown_member", who=html.escape(who))


async def reply_with_record(
    message: Message, bot: Bot, session: AsyncSession, receipt: Receipt, sender: User | None, prefix: str = ""
) -> None:
    """Answers with the record, remembers the answer (replying to it edits the record) and
    sends the budget warnings this record caused."""
    reply = await message.reply(
        prefix + await format_receipt(session, receipt, sender.id if sender else None),
        reply_markup=receipt_keyboard(receipt.id),
    )
    receipt.bot_message_id = reply.message_id
    await session.commit()
    await send_alerts(bot, message.chat.id, await new_budget_alerts(session, receipt))


async def react(message: Message, emoji: str):
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except TelegramBadRequest:
        pass
