"""Records typed in the chat (`/add`, `+`, `/income`), edits by replying, delete and duplicate buttons."""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReactionTypeEmoji
from sqlalchemy import or_, select

from app.bot.common import callback_arg, callback_message, get_sender, reply_with_record, send_alerts, unknown_member
from app.bot.ui import format_receipt, receipt_keyboard
from app.db.models import Receipt
from app.db.session import session_factory
from app.i18n import t
from app.receipts.service import ReceiptService, parse_manual_text, split_who
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)
router = Router()


async def _book_text(message: Message, bot: Bot, text: str, *, income: bool):
    """`/add`, `+ ...` (an expense) and `/income` (an income): "[Name:] description amount"."""
    text = text.strip()
    usage = t("bot.usage_income") if income else t("bot.usage_add")
    if not text and not income:
        await message.reply(t("bot.format", usage=usage))
        return
    async with session_factory()() as session:
        svc = ReceiptService(session)
        sender = await get_sender(svc, message)
        owner = sender
        who, rest = split_who(text)
        if who:
            owner = await svc.find_user(who)
            if owner is None:
                await message.reply(unknown_member(who))
                return
            text = rest
        add = svc.add_income_text if income else svc.add_manual_text
        r = await add(text, owner, message.chat.id, message.message_id)
        if r is None:
            await message.reply(t("bot.format" if income else "bot.bad_amount", usage=usage))
            return
        await reply_with_record(message, bot, session, r, sender)


@router.message(Command("income", "доход"))
async def on_income(message: Message, bot: Bot, command: CommandObject):
    await _book_text(message, bot, command.args or "", income=True)


@router.message(Command("add"))
async def on_add(message: Message, bot: Bot, command: CommandObject):
    await _book_text(message, bot, command.args or "", income=False)


@router.message(F.text.startswith("+"))
async def on_plus(message: Message, bot: Bot):
    await _book_text(message, bot, (message.text or "")[1:], income=False)


@router.message(F.reply_to_message, F.text, ~F.text.startswith("/"))
async def on_reply_edit(message: Message, bot: Bot):
    """Reply to the bot's message about a record (or to the receipt photo) to edit it."""
    if message.reply_to_message is None:
        return
    target = message.reply_to_message.message_id
    async with session_factory()() as session:
        r = await session.scalar(
            select(Receipt).where(
                Receipt.chat_id == message.chat.id,
                or_(Receipt.bot_message_id == target, Receipt.message_id == target),
            )
        )
        if r is None:
            return  # an ordinary conversation, not about a receipt
        svc = ReceiptService(session)
        sender = await get_sender(svc, message)
        text = (message.text or "").strip()

        who, rest = split_who(text)
        if who:
            owner = await svc.find_user(who)
            if owner is None:
                await message.reply(unknown_member(who))
                return
            r.user_id = owner.id
            await session.commit()
            text = rest

        if text:
            quick = parse_manual_text(text)
            items = await r.awaitable_attrs.items
            if quick and quick[0] is None:
                if len(items) != 1:
                    await message.reply(t("bot.amount_single_only"))
                    return
                items[0].total = items[0].unit_price = quick[1]
                r.total = quick[1]
                await session.commit()
            else:
                await svc.set_description(r, text)

        new_text = await format_receipt(session, r, sender.id if sender else None)
        if r.bot_message_id:
            try:
                await bot.edit_message_text(
                    new_text,
                    chat_id=message.chat.id,
                    message_id=r.bot_message_id,
                    reply_markup=receipt_keyboard(r.id),
                )
                await message.react([ReactionTypeEmoji(emoji="👌")])
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                log.warning("could not update bot message: %s", e)
        await message.reply(new_text, reply_markup=receipt_keyboard(r.id))


@router.callback_query(F.data.startswith("dupdel:"))
async def on_duplicate_delete(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    async with session_factory()() as session:
        r = await session.get(Receipt, int(callback_arg(cb)))
        if r:
            await ReceiptService(session).delete_receipt(r)
    await msg.edit_text(t("bot.dup_deleted"))
    await cb.answer(t("bot.cb_deleted"))


@router.callback_query(F.data.startswith("dupkeep:"))
async def on_duplicate_keep(cb: CallbackQuery, bot: Bot):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    rid = int(callback_arg(cb))
    await msg.edit_reply_markup(reply_markup=receipt_keyboard(rid))
    await cb.answer(t("bot.cb_kept"))
    async with session_factory()() as session:
        r = await session.get(Receipt, rid)
        if r:
            await send_alerts(bot, msg.chat.id, await new_budget_alerts(session, r))


@router.callback_query(F.data.startswith("del:"))
async def on_delete_ask(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    rid = callback_arg(cb)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("bot.yes_delete"), callback_data=f"delok:{rid}"),
                InlineKeyboardButton(text=t("bot.cancel"), callback_data=f"keep:{rid}"),
            ]
        ]
    )
    await msg.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("keep:"))
async def on_delete_cancel(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    await msg.edit_reply_markup(reply_markup=receipt_keyboard(int(callback_arg(cb))))
    await cb.answer(t("bot.cb_kept"))


@router.callback_query(F.data.startswith("delok:"))
async def on_delete(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    rid = int(callback_arg(cb))
    async with session_factory()() as session:
        r = await session.get(Receipt, rid)
        if r:
            await ReceiptService(session).delete_receipt(r)
    await msg.edit_text(t("bot.record_deleted"))
    await cb.answer(t("bot.cb_deleted"))


