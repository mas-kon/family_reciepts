import asyncio
import html
import logging
import secrets
from collections import OrderedDict

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReactionTypeEmoji,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bank import (
    analyse_statement,
    book_statement,
    delete_import,
    handle_bank_text,
    looks_like_bank_message,
    looks_like_statement,
    statement_text,
)
from app.bot.ui import format_receipt, money, receipt_keyboard
from app.config import get_settings
from app.constants import Kind
from app.db.models import Receipt, User
from app.db.session import session_factory
from app.llm.client import LLMError
from app.receipts.service import (
    ProcessResult,
    ReceiptService,
    parse_manual_text,
    split_who,
)
from app.stats import new_budget_alerts
from app.voice import MAX_VOICE_SECONDS, handle_voice, to_wav

log = logging.getLogger(__name__)

# free LLM tiers are rate limited: do not hammer them when someone sends an album
_llm_slots = asyncio.Semaphore(2)


HELP = (
    "<b>Чек.</b> Пришлите фото чека, я распознаю покупки и запишу их. "
    "Лучше снимать чек целиком, вместе с QR-кодом. "
    "Подпись к фото станет описанием: <i>овощи на рынке</i>.\n\n"
    "<b>Трата без чека:</b> <code>/add такси 12</code> или <code>+ кофе 3.50</code>. "
    "Можно одной суммой: <code>+ 12</code>, она попадёт в «Без категории».\n\n"
    "<b>Доход:</b> <code>/income зарплата 1500</code>, "
    "<code>/income Маша: подработка 200</code>.\n\n"
    "<b>За другого члена семьи:</b> <code>+ Маша: кино 12</code>, "
    "у фото подпись <code>Маша: тетради</code>.\n\n"
    "<b>Голосом:</b> «двенадцать евро такси» или «Маше на кино пятнадцать».\n\n"
    "<b>Банк:</b> перешлите сюда SMS или уведомление банка о списании или поступлении, я запишу его. "
    "Если она уже записана по чеку, просто скажу об этом. Или: <code>/bank текст уведомления</code>.\n\n"
    "<b>Выписка:</b> пришлите PDF-выписку из банка, я покажу, какие расходы и доходы ещё не записаны, "
    "и запишу их по кнопке. Переводы членам семьи в расходы не входят: "
    "укажите в вебе, как банк пишет их имена (Настройки → Семья).\n\n"
    "<b>PDF-чек</b> или скриншот заказа присылайте как обычный чек.\n\n"
    "<b>Исправить запись:</b> ответьте на моё сообщение о ней:\n"
    "• текстом, это будет описание;\n"
    "• числом, это новая сумма записи из одной строки;\n"
    "• <code>Маша:</code>, чтобы записать трату на Машу.\n\n"
    "Все суммы в евро."
)


def _allowed(chat_id: int) -> bool:
    """Only the configured family chats. An empty list is open to every chat in dev mode
    (AUTH_DISABLED) only; otherwise the bot answers just /chatid until it is filled in."""
    s = get_settings()
    return chat_id in s.allowed_chats if s.allowed_chats else s.auth_disabled


class AllowedChatsOnly(BaseMiddleware):
    """Drops updates from chats that are not the family's, before any handler runs. The
    commands that help to set the bot up work everywhere."""

    OPEN_COMMANDS = ("/start", "/help", "/chatid")

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None
        else:
            chat = event.chat
            if (event.text or "").startswith(self.OPEN_COMMANDS):
                return await handler(event, data)
        if chat is not None and _allowed(chat.id):
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer()
        return None


router = Router()
router.message.outer_middleware(AllowedChatsOnly())
router.callback_query.outer_middleware(AllowedChatsOnly())


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
    return f"Не знаю, кто такой «{html.escape(who)}». Добавьте члена семьи в вебе: Настройки → Семья."


@router.message(Command("start", "help"))
async def on_help(message: Message):
    await message.reply(HELP)


@router.message(Command("chatid"))
async def on_chatid(message: Message):
    await message.reply(f"ID этого чата: <code>{message.chat.id}</code>")


@router.message(F.photo)
async def on_photo(message: Message, bot: Bot):
    await _handle_image(message, bot, message.photo[-1].file_id, "jpg")


@router.message(F.document.mime_type.startswith("image/"))
async def on_image_document(message: Message, bot: Bot):
    ext = (message.document.mime_type or "image/jpeg").split("/")[-1].replace("jpeg", "jpg")
    await _handle_image(message, bot, message.document.file_id, ext)


@router.message(F.document.mime_type == "application/pdf")
async def on_pdf(message: Message, bot: Bot):
    data = (await bot.download(message.document.file_id)).read()
    try:
        text = await asyncio.to_thread(statement_text, data, "x.pdf")
    except Exception:
        text = ""  # a scan: read it as a receipt picture
    if looks_like_statement(text):
        await _statement(message, text)
        return
    await _handle_image(message, bot, message.document.file_id, "pdf", data=data)


# ---------- bank statements ----------

# statements waiting for "Записать": token -> (chat_id, sender, transactions, their external ids, ids of the whole statement). Kept in memory: after a
# restart the button asks to send the statement again.
_statements: OrderedDict[str, tuple[int, object, list, list, set]] = OrderedDict()
MAX_PENDING_STATEMENTS = 20
MAX_STATEMENT_LINES = 25


def _tx_line(tx) -> str:
    when = f"{tx.date:%d.%m}" if tx.date else "—"
    return f"{when} {html.escape(tx.merchant or 'Оплата')} — {money(tx.amount)}"


STATEMENT_GROUPS = [
    ("expense", "💸 Расходы"),
    ("income", "💰 Доходы"),
    ("transfer", "👨‍👩‍👧 Внутри семьи, в расходы не войдут"),
]


def statement_summary(rows) -> tuple[str, list]:
    """Message about an analysed statement and the rows to book."""
    booked_kinds = [r for r in rows if r.kind]
    new = [r for r in booked_kinds if not r.match]
    own = len(rows) - len(booked_kinds)
    lines = [f"🏦 <b>Выписка.</b> Операций: {len(booked_kinds)}, уже записано: {len(booked_kinds) - len(new)}."]
    if own:
        lines.append(f"Между своими счетами: {own}, их не учитываю.")
    if not new:
        lines.append("Всё уже записано, добавлять нечего.")
        return "\n".join(lines), []
    shown = 0
    for kind, title in STATEMENT_GROUPS:
        group = [r for r in new if r.kind == kind]
        if not group:
            continue
        lines.append(f"\n{title} ({len(group)}, {sum(r.tx.amount for r in group):.2f} €):")
        for r in group:
            if shown >= MAX_STATEMENT_LINES:
                break
            peer = f" → {html.escape(r.peer.name)}" if r.peer else ""
            lines.append(f"• {_tx_line(r.tx)}{peer}")
            shown += 1
    if shown < len(new):
        lines.append(f"…и ещё {len(new) - shown}")
    if any(r.kind == Kind.EXPENSE and r.tx.type == "transfer_out" for r in new):
        lines.append(
            "\n<i>Переводы людям считаю расходами. Если это кто-то из семьи, укажите, как его пишет "
            "банк: в вебе Настройки → Семья. Тогда его переводы не войдут в расходы.</i>"
        )
    lines.append("\nЗаписать? Выбрать отдельные строки можно в вебе, на странице «Выписка».")
    return "\n".join(lines), new


async def _statement(message: Message, text: str):
    status = await message.reply("⏳ Читаю выписку…")
    try:
        async with _llm_slots, session_factory()() as session:
            rows = await analyse_statement(ReceiptService(session), text)
            summary, new = statement_summary(rows)
    except LLMError as e:
        log.warning("statement failed: %s", e)
        await _edit(status, "❌ Нейросеть не ответила, попробуйте позже или загрузите выписку в вебе.")
        return
    except Exception:
        log.exception("failed to read statement")
        await _edit(status, "❌ Не удалось прочитать выписку.")
        return
    if not rows:
        await _edit(status, "🏦 Это выписка, но операций в ней не нашёл. Ничего не записал.")
        return
    if not new:
        await _edit(status, summary)
        return
    token = secrets.token_hex(4)
    _statements[token] = (
        message.chat.id,
        message.from_user or None,
        [r.tx for r in new],
        [r.external_id for r in new],
        {r.external_id for r in rows},
    )
    while len(_statements) > MAX_PENDING_STATEMENTS:
        _statements.popitem(last=False)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✅ Записать ({len(new)})", callback_data=f"stmt:{token}"),
                InlineKeyboardButton(text="Не надо", callback_data=f"stmtno:{token}"),
            ]
        ]
    )
    await _edit(status, summary, kb)


@router.callback_query(F.data.startswith("stmt:"))
async def on_statement_book(cb: CallbackQuery, bot: Bot):
    if not cb.message:
        return await cb.answer()
    pending = _statements.pop(cb.data.split(":", 1)[1], None)
    if pending is None or pending[0] != cb.message.chat.id:
        await cb.message.edit_reply_markup(reply_markup=None)
        return await cb.answer("Выписка устарела, пришлите её ещё раз", show_alert=True)
    async with session_factory()() as session:
        svc = ReceiptService(session)
        # expenses go to whoever sent the statement, unless the card belongs to someone else
        u = pending[1] or cb.from_user
        sender = await svc.get_or_create_user(u.id, u.full_name, u.username)
        booked, skipped = await book_statement(
            svc, pending[2], sender, chat_id=cb.message.chat.id, ids=pending[3], batch_ids=pending[4]
        )
        await session.commit()
        import_id = booked[0].import_id if booked else None
        alerts = []
        for r in booked:
            alerts += await new_budget_alerts(session, r)
    text = (cb.message.html_text or "").split("\n\nЗаписать?")[0]
    text += f"\n\n✅ Записано: {len(booked)}" + (f", уже были: {skipped}" if skipped else "") + "."
    await cb.message.edit_text(text, reply_markup=_import_keyboard(import_id) if import_id else None)
    await cb.answer("Записано")
    await _send_alerts(bot, cb.message.chat.id, alerts)


def _import_keyboard(import_id: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="🗑 Удалить всю выписку", callback_data=f"impdel:{import_id}")]
    base = get_settings().web_base_url.rstrip("/")
    if base:
        row.append(InlineKeyboardButton(text="🔎 Открыть", url=f"{base}/receipts?import_id={import_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


@router.callback_query(F.data.startswith("impdel:"))
async def on_import_delete_ask(cb: CallbackQuery):
    if not cb.message:
        return await cb.answer()
    iid = cb.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить все записи", callback_data=f"impdelok:{iid}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"impkeep:{iid}"),
            ]
        ]
    )
    await cb.message.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("impkeep:"))
async def on_import_keep(cb: CallbackQuery):
    if not cb.message:
        return await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=_import_keyboard(cb.data.split(":", 1)[1]))
    await cb.answer("Оставил")


@router.callback_query(F.data.startswith("impdelok:"))
async def on_import_delete(cb: CallbackQuery):
    if not cb.message:
        return await cb.answer()
    async with session_factory()() as session:
        deleted = await delete_import(session, cb.data.split(":", 1)[1])
    text = (cb.message.html_text or "").split("\n\n✅ Записано")[0]
    await cb.message.edit_text(f"{text}\n\n🗑 Выписка удалена, записей: {deleted}.", reply_markup=None)
    await cb.answer("Удалено")


@router.callback_query(F.data.startswith("stmtno:"))
async def on_statement_skip(cb: CallbackQuery):
    if not cb.message:
        return await cb.answer()
    _statements.pop(cb.data.split(":", 1)[1], None)
    if cb.message:
        await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Ничего не записал")


async def _handle_image(message: Message, bot: Bot, file_id: str, ext: str, data: bytes | None = None):
    status = await message.reply("⏳ Распознаю чек…")
    try:
        if data is None:
            data = (await bot.download(file_id)).read()
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
                await _edit(status, f"♻️ Этот чек уже записан{when}.", receipt_keyboard(d.id))
                return
            if res.not_receipt:
                await _edit(
                    status,
                    "🤔 Не похоже на чек, ничего не записал. "
                    "Выписку из банка присылайте PDF-файлом или загрузите в вебе.",
                )
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


async def _reply_with_record(
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
    await _send_alerts(bot, message.chat.id, await new_budget_alerts(session, receipt))


async def _book_text(message: Message, bot: Bot, text: str, *, income: bool):
    """`/add`, `+ ...` (an expense) and `/income` (an income): "[Name:] description amount"."""
    text = text.strip()
    usage = "<code>/income зарплата 1500</code>" if income else "<code>/add такси 12</code> или <code>+ 12</code>"
    if not text and not income:
        await message.reply(f"Формат: {usage}")
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
        add = svc.add_income_text if income else svc.add_manual_text
        r = await add(text, owner, message.chat.id, message.message_id)
        if r is None:
            await message.reply(("Формат: " if income else "Не понял сумму. Формат: ") + usage)
            return
        await _reply_with_record(message, bot, session, r, sender)


@router.message(Command("income", "доход"))
async def on_income(message: Message, bot: Bot, command: CommandObject):
    await _book_text(message, bot, command.args or "", income=True)


@router.message(Command("add"))
async def on_add(message: Message, bot: Bot, command: CommandObject):
    await _book_text(message, bot, command.args or "", income=False)


@router.message(F.text.startswith("+"))
async def on_plus(message: Message, bot: Bot):
    await _book_text(message, bot, message.text[1:], income=False)


@router.message(F.reply_to_message, F.text, ~F.text.startswith("/"))
async def on_reply_edit(message: Message, bot: Bot):
    """Reply to the bot's message about a record (or to the receipt photo) to edit it."""
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


@router.callback_query(F.data.startswith("del:"))
async def on_delete_ask(cb: CallbackQuery):
    if not cb.message:
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
    if not cb.message:
        return await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=receipt_keyboard(int(cb.data.split(":")[1])))
    await cb.answer("Оставил")


@router.callback_query(F.data.startswith("delok:"))
async def on_delete(cb: CallbackQuery):
    if not cb.message:
        return await cb.answer()
    rid = int(cb.data.split(":")[1])
    async with session_factory()() as session:
        r = await session.get(Receipt, rid)
        if r:
            await ReceiptService(session).delete_receipt(r)
    await cb.message.edit_text("🗑 Запись удалена.")
    await cb.answer("Удалено")


# ---------- voice ----------


@router.message(F.voice | F.audio)
async def on_voice(message: Message, bot: Bot):
    if not get_settings().audio_models:
        return
    media = message.voice or message.audio
    if media.duration and media.duration > MAX_VOICE_SECONDS:
        return  # a long voice message is a conversation, not an expense
    try:
        data = (await bot.download(media.file_id)).read()
        wav = await asyncio.to_thread(to_wav, data)
        async with _llm_slots, session_factory()() as session:
            svc = ReceiptService(session)
            sender = await _sender(svc, message)
            res = await handle_voice(svc, wav, sender, chat_id=message.chat.id, message_id=message.message_id)
            if res.receipt is None:
                if res.problem and res.problem.startswith("Не знаю"):
                    await message.reply(f"{html.escape(res.problem)}. Услышал: «{html.escape(res.transcript)}»")
                else:
                    # most likely an ordinary voice message without an expense: stay quiet
                    await _react(message, "🤔")
                return
            await _reply_with_record(message, bot, session, res.receipt, sender)
    except Exception:
        log.exception("failed to process voice message")
        await _react(message, "🤷")


async def _react(message: Message, emoji: str):
    try:
        await message.react([ReactionTypeEmoji(emoji=emoji)])
    except TelegramBadRequest:
        pass


# ---------- bank notifications ----------


async def _bank(message: Message, bot: Bot, text: str, explicit: bool):
    async with session_factory()() as session:
        svc = ReceiptService(session)
        sender = await _sender(svc, message)
        try:
            results = await handle_bank_text(svc, text, sender, chat_id=message.chat.id, message_id=message.message_id)
        except LLMError as e:
            log.warning("bank message failed: %s", e)
            if explicit:
                await message.reply("❌ Нейросеть не ответила, попробуйте позже.")
            return
        if not results:
            if explicit:
                await message.reply("Не нашёл в тексте операций, которые надо записать.")
            return
        for r in results:
            if r.match:
                m = r.match
                when = f" от {m.purchased_at:%d.%m}" if m.purchased_at else ""
                what = {"income": "Поступление", "transfer": "Перевод"}.get(r.kind, "Списание")
                where = f" ({html.escape(r.tx.merchant)})" if r.tx.merchant else ""
                await message.reply(
                    f"🏦 {what} {money(r.tx.amount)}{where} уже записано{when}.",
                    reply_markup=receipt_keyboard(m.id),
                )
                continue
            await _reply_with_record(message, bot, session, r.receipt, sender, prefix="🏦 ")


@router.message(Command("bank"))
async def on_bank_command(message: Message, bot: Bot, command: CommandObject):
    text = (command.args or "").strip()
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption or ""
    if not text:
        await message.reply("Формат: <code>/bank текст уведомления банка</code> или ответьте /bank на уведомление.")
        return
    await _bank(message, bot, text, explicit=True)


@router.message(F.text.func(looks_like_bank_message))
async def on_bank_text(message: Message, bot: Bot):
    await _bank(message, bot, message.text, explicit=False)
