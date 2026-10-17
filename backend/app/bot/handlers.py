import asyncio
import html
import logging
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    ReactionTypeEmoji,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Category, Receipt, User
from app.db.session import session_factory
from app.receipts.service import ProcessResult, ReceiptService, parse_manual_text, split_who
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)
router = Router()

# free LLM tiers are rate limited: do not hammer them when someone sends an album
_llm_slots = asyncio.Semaphore(2)


HELP = (
    "<b>Чек.</b> Пришлите фото чека, я распознаю покупки и запишу их. "
    "Лучше снимать чек целиком, вместе с QR-кодом. "
    "Подпись к фото станет описанием: <i>овощи на рынке</i>.\n\n"
    "<b>Трата без чека:</b> <code>/add такси 12</code> или <code>+ кофе 3.50</code>. "
    "Можно одной суммой: <code>+ 12</code>, она попадёт в «Без категории».\n\n"
    "<b>За другого члена семьи:</b> <code>+ Маша: кино 12</code>, "
    "у фото подпись <code>Маша: тетради</code>.\n\n"
    "<b>Исправить запись:</b> ответьте на моё сообщение о ней:\n"
    "• текстом, это будет описание;\n"
    "• числом, это новая сумма записи из одной строки;\n"
    "• <code>Маша:</code>, чтобы записать трату на Машу.\n\n"
    "Все суммы в евро."
)


def money(amount: float | None) -> str:
    return "?" if amount is None else f"{amount:.2f} €"


def _allowed(chat_id: int) -> bool:
    chats = get_settings().allowed_chats
    return not chats or chat_id in chats


def receipt_keyboard(receipt_id: int) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{receipt_id}")]
    base = get_settings().web_base_url.rstrip("/")
    if base:
        row.append(InlineKeyboardButton(text="🔎 Открыть", url=f"{base}/receipts/{receipt_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def _category_names(session: AsyncSession) -> dict[int, str]:
    cats = {c.id: c for c in await session.scalars(select(Category))}
    return {cid: (cats[c.parent_id].name if c.parent_id else c.name) for cid, c in cats.items()}


async def format_receipt(session: AsyncSession, r: Receipt, sender_id: int | None = None) -> str:
    names = await _category_names(session)
    items = await r.awaitable_attrs.items
    by_cat: dict[str, float] = defaultdict(float)
    for it in items:
        by_cat[names.get(it.category_id, "Без категории")] += it.total
    head = "✅" if r.status == "ok" else "⚠️"
    when = f"{r.purchased_at:%d.%m %H:%M}" if r.purchased_at else ""
    if r.store:
        title = r.store
    elif r.source != "photo" and items:
        title = items[0].name_ru or items[0].name_original
    else:
        title = "Чек"
    lines = [
        f"{head} <b>{html.escape(title)}</b> · {when}".rstrip(" ·"),
        f"{money(r.total)} · позиций: {len(items)}",
    ]
    top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:4]
    if top:
        lines.append(", ".join(f"{k} {v:.2f}" for k, v in top))
    if r.note and r.note != title:
        lines.append(f"📝 {html.escape(r.note)}")
    if r.user_id and r.user_id != sender_id:
        owner = await session.get(User, r.user_id)
        if owner:
            lines.append(f"👤 {html.escape(owner.name)}")
    if r.status == "needs_review" and r.review_reason:
        lines.append(f"\n<i>Проверьте в вебе: {html.escape(r.review_reason)}</i>")
    return "\n".join(lines)


async def _edit(msg: Message, text: str, kb: InlineKeyboardMarkup | None = None):
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" in str(e):
            return
        # e.g. Telegram rejects a URL button: retry without the keyboard
        log.warning("edit failed (%s), retrying without keyboard", e)
        await msg.edit_text(text)


async def _send_alerts(bot: Bot, chat_id: int, alerts: list[str]):
    for a in alerts:
        await bot.send_message(chat_id, a)


async def _sender(svc: ReceiptService, message: Message) -> User | None:
    u = message.from_user
    if not u:
        return None
    user = await svc.get_or_create_user(u.id, u.full_name, u.username)
    await svc.session.commit()
    return user


def _unknown_member(who: str) -> str:
    return (
        f"Не знаю, кто такой «{html.escape(who)}». "
        "Добавьте члена семьи в вебе: Настройки → Семья."
    )


@router.message(Command("start", "help"))
async def on_help(message: Message):
    await message.reply(HELP)


@router.message(Command("chatid"))
async def on_chatid(message: Message):
    await message.reply(f"ID этого чата: <code>{message.chat.id}</code>")


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot):
    if not _allowed(message.chat.id):
        return
    await _handle_image(message, bot, message.photo[-1].file_id, "jpg")


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_document(message: Message, bot: Bot):
    if not _allowed(message.chat.id):
        return
    ext = (message.document.mime_type or "image/jpeg").split("/")[-1].replace("jpeg", "jpg")
    await _handle_image(message, bot, message.document.file_id, ext)


async def _handle_image(message: Message, bot: Bot, file_id: str, ext: str):
    status = await message.reply("⏳ Распознаю чек…")
    try:
        buf = await bot.download(file_id)
        data = buf.read()
        async with _llm_slots, session_factory()() as session:
            svc = ReceiptService(session)
            sender = await _sender(svc, message)
            # caption "Маша: тетради" books the receipt for Маша with description "тетради"
            caption = (message.caption or "").strip()
            owner, note = sender, caption
            who, rest = split_who(caption)
            if who:
                found = await svc.find_user(who)
                if found:
                    owner, note = found, rest
            res: ProcessResult = await svc.process_photo(
                data, owner, chat_id=message.chat.id, message_id=message.message_id, ext=ext,
                note=note or None,
            )
            if res.duplicate_of:
                d = res.duplicate_of
                when = f" от {d.purchased_at:%d.%m.%Y}" if d.purchased_at else ""
                await _edit(status, f"♻️ Этот чек уже записан{when}.", receipt_keyboard(d.id))
                return
            if res.not_receipt:
                await _edit(status, "🤔 Не похоже на чек, ничего не записал.")
                return
            res.receipt.bot_message_id = status.message_id
            await session.commit()
            if res.error:
                await _edit(
                    status,
                    "❌ Не удалось распознать: нейросеть недоступна.\n"
                    "Фото сохранено, распознавание можно повторить в вебе.",
                    receipt_keyboard(res.receipt.id),
                )
                return
            text = await format_receipt(session, res.receipt, sender.id if sender else None)
            await _edit(status, text, receipt_keyboard(res.receipt.id))
            await _send_alerts(bot, message.chat.id, await new_budget_alerts(session, res.receipt))
    except Exception:
        log.exception("failed to process receipt")
        await _edit(status, "❌ Что-то пошло не так при обработке чека.")


async def _manual(message: Message, bot: Bot, text: str):
    if not _allowed(message.chat.id):
        return
    text = text.strip()
    if not text:
        await message.reply("Формат: <code>/add такси 12</code> или <code>+ 12</code>")
        return
    async with session_factory()() as session:
        svc = ReceiptService(session)
        sender = await _sender(svc, message)
        owner = sender
        who, rest = split_who(text)
        if who:
            owner = await svc.find_user(who)
            if owner is None:
                await message.reply(_unknown_member(who))
                return
            text = rest
        r = await svc.add_manual_text(text, owner, message.chat.id, message.message_id)
        if r is None:
            await message.reply("Не понял сумму. Формат: <code>/add такси 12</code> или <code>+ 12</code>")
            return
        reply = await message.reply(
            await format_receipt(session, r, sender.id if sender else None),
            reply_markup=receipt_keyboard(r.id),
        )
        r.bot_message_id = reply.message_id
        await session.commit()
        await _send_alerts(bot, message.chat.id, await new_budget_alerts(session, r))


@router.message(Command("add"))
async def on_add(message: Message, bot: Bot, command: CommandObject):
    await _manual(message, bot, command.args or "")


@router.message(F.text.startswith("+"))
async def on_plus(message: Message, bot: Bot):
    await _manual(message, bot, message.text[1:])


@router.message(F.reply_to_message, F.text, ~F.text.startswith("/"))
async def on_reply_edit(message: Message, bot: Bot):
    """Reply to the bot's message about a record (or to the receipt photo) to edit it."""
    if not _allowed(message.chat.id):
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
        sender = await _sender(svc, message)
        text = message.text.strip()

        who, rest = split_who(text)
        if who:
            owner = await svc.find_user(who)
            if owner is None:
                await message.reply(_unknown_member(who))
                return
            r.user_id = owner.id
            await session.commit()
            text = rest

        if text:
            quick = parse_manual_text(text)
            items = await r.awaitable_attrs.items
            if quick and quick[0] is None:
                if len(items) != 1:
                    await message.reply("Сумму можно поменять только у записи из одной строки. Чек правится в вебе.")
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
                    new_text, chat_id=message.chat.id, message_id=r.bot_message_id,
                    reply_markup=receipt_keyboard(r.id),
                )
                await message.react([ReactionTypeEmoji(emoji="👌")])
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                log.warning("could not update bot message: %s", e)
        await message.reply(new_text, reply_markup=receipt_keyboard(r.id))


@router.callback_query(F.data.startswith("del:"))
async def on_delete_ask(cb: CallbackQuery):
    if not cb.message or not _allowed(cb.message.chat.id):
        return await cb.answer()
    rid = cb.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить", callback_data=f"delok:{rid}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"keep:{rid}"),
            ]
        ]
    )
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("keep:"))
async def on_delete_cancel(cb: CallbackQuery):
    await cb.message.edit_reply_markup(reply_markup=receipt_keyboard(int(cb.data.split(":")[1])))
    await cb.answer("Оставил")


@router.callback_query(F.data.startswith("delok:"))
async def on_delete(cb: CallbackQuery):
    if not cb.message or not _allowed(cb.message.chat.id):
        return await cb.answer()
    rid = int(cb.data.split(":")[1])
    async with session_factory()() as session:
        r = await session.get(Receipt, rid)
        if r:
            await ReceiptService(session).delete_receipt(r)
    await cb.message.edit_text("🗑 Запись удалена.")
    await cb.answer("Удалено")
