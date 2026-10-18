"""Bank statements sent to the group: analysis, booking by button, deleting a whole import."""

import html
import logging
import secrets
from collections import OrderedDict
from dataclasses import dataclass

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.types import User as TgUser

from app.bank import analyse_statement, book_statement, delete_import
from app.bot.common import callback_arg, callback_message, edit, llm_slots, send_alerts
from app.bot.ui import money
from app.config import get_settings
from app.constants import Kind
from app.db.session import session_factory
from app.llm.client import LLMError
from app.llm.schema import ParsedBankTx
from app.receipts.service import ReceiptService
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)
router = Router()


@dataclass
class PendingStatement:
    chat_id: int
    sender: TgUser | None
    transactions: list[ParsedBankTx]  # the ones to book
    ids: list[str]  # their external ids
    batch_ids: set[str]  # ids of the whole statement


# statements waiting for "Записать", by button token. Kept in memory: after a restart the button
# asks to send the statement again.
_statements: OrderedDict[str, PendingStatement] = OrderedDict()
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


async def read_statement(message: Message, text: str):
    status = await message.reply("⏳ Читаю выписку…")
    try:
        async with llm_slots, session_factory()() as session:
            rows = await analyse_statement(ReceiptService(session), text)
            summary, new = statement_summary(rows)
    except LLMError as e:
        log.warning("statement failed: %s", e)
        await edit(status, "❌ Нейросеть не ответила, попробуйте позже или загрузите выписку в вебе.")
        return
    except Exception:
        log.exception("failed to read statement")
        await edit(status, "❌ Не удалось прочитать выписку.")
        return
    if not rows:
        await edit(status, "🏦 Это выписка, но операций в ней не нашёл. Ничего не записал.")
        return
    if not new:
        await edit(status, summary)
        return
    token = secrets.token_hex(4)
    _statements[token] = PendingStatement(
        chat_id=message.chat.id,
        sender=message.from_user,
        transactions=[r.tx for r in new],
        ids=[r.external_id for r in new],
        batch_ids={r.external_id for r in rows},
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
    await edit(status, summary, kb)


@router.callback_query(F.data.startswith("stmt:"))
async def on_statement_book(cb: CallbackQuery, bot: Bot):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    pending = _statements.pop(callback_arg(cb), None)
    if pending is None or pending.chat_id != msg.chat.id:
        await msg.edit_reply_markup(reply_markup=None)
        return await cb.answer("Выписка устарела, пришлите её ещё раз", show_alert=True)
    async with session_factory()() as session:
        svc = ReceiptService(session)
        # expenses go to whoever sent the statement, unless the card belongs to someone else
        u = pending.sender or cb.from_user
        sender = await svc.get_or_create_user(u.id, u.full_name, u.username)
        booked, skipped = await book_statement(
            svc, pending.transactions, sender, chat_id=msg.chat.id, ids=pending.ids, batch_ids=pending.batch_ids
        )
        await session.commit()
        import_id = booked[0].import_id if booked else None
        alerts = []
        for r in booked:
            alerts += await new_budget_alerts(session, r)
    text = (msg.html_text or "").split("\n\nЗаписать?")[0]
    text += f"\n\n✅ Записано: {len(booked)}" + (f", уже были: {skipped}" if skipped else "") + "."
    await msg.edit_text(text, reply_markup=_import_keyboard(import_id) if import_id else None)
    await cb.answer("Записано")
    await send_alerts(bot, msg.chat.id, alerts)


def _import_keyboard(import_id: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(text="🗑 Удалить всю выписку", callback_data=f"impdel:{import_id}")]
    base = get_settings().web_base_url.rstrip("/")
    if base:
        row.append(InlineKeyboardButton(text="🔎 Открыть", url=f"{base}/receipts?import_id={import_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[row])


@router.callback_query(F.data.startswith("impdel:"))
async def on_import_delete_ask(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    iid = callback_arg(cb)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, удалить все записи", callback_data=f"impdelok:{iid}"),
                InlineKeyboardButton(text="Отмена", callback_data=f"impkeep:{iid}"),
            ]
        ]
    )
    await msg.edit_reply_markup(reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("impkeep:"))
async def on_import_keep(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    await msg.edit_reply_markup(reply_markup=_import_keyboard(callback_arg(cb)))
    await cb.answer("Оставил")


@router.callback_query(F.data.startswith("impdelok:"))
async def on_import_delete(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    async with session_factory()() as session:
        deleted = await delete_import(session, callback_arg(cb))
    text = (msg.html_text or "").split("\n\n✅ Записано")[0]
    await msg.edit_text(f"{text}\n\n🗑 Выписка удалена, записей: {deleted}.", reply_markup=None)
    await cb.answer("Удалено")


@router.callback_query(F.data.startswith("stmtno:"))
async def on_statement_skip(cb: CallbackQuery):
    if (msg := callback_message(cb)) is None:
        return await cb.answer()
    _statements.pop(callback_arg(cb), None)
    await msg.edit_reply_markup(reply_markup=None)
    await cb.answer("Ничего не записал")
