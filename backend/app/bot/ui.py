"""Bot messages and buttons: shared by the handlers, the scheduler jobs and the e-mail poller."""

import html
from collections import defaultdict

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.constants import Kind
from app.db.models import Category, Receipt, User


def money(amount: float | None) -> str:
    return "?" if amount is None else f"{amount:.2f} €"


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
    if r.kind == Kind.INCOME:
        head = "💰"
    elif r.kind == Kind.TRANSFER:
        head = "👨‍👩‍👧"
    when = f"{r.purchased_at:%d.%m %H:%M}" if r.purchased_at else ""
    if r.store:
        title = r.store
    elif r.source != "photo" and items:
        title = items[0].name_ru or items[0].name_original
    else:
        title = "Чек"
    lines = [f"{head} <b>{html.escape(title)}</b> · {when}".rstrip(" ·")]
    if r.kind == Kind.INCOME:
        lines.append(f"Доход {money(r.total)}")
    elif r.kind == Kind.TRANSFER:
        peer = await session.get(User, r.peer_user_id) if r.peer_user_id else None
        to = f" ({html.escape(peer.name)})" if peer else ""
        lines.append(f"Перевод внутри семьи{to}: {money(r.total)}, в расходы не входит")
    else:
        lines.append(f"{money(r.total)} · позиций: {len(items)}")
    top = sorted(by_cat.items(), key=lambda kv: -kv[1])[:4]
    if top:
        lines.append(", ".join(f"{html.escape(k)} {v:.2f}" for k, v in top))
    if r.note and r.note != title:
        lines.append(f"📝 {html.escape(r.note)}")
    if r.user_id and r.user_id != sender_id:
        owner = await session.get(User, r.user_id)
        if owner:
            lines.append(f"👤 {html.escape(owner.name)}")
    if r.status == "needs_review" and r.review_reason:
        lines.append(f"\n<i>Проверьте в вебе: {html.escape(r.review_reason)}</i>")
    return "\n".join(lines)


def duplicate_keyboard(new_id: int, old_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🗑 Да, дубль — удалить", callback_data=f"dupdel:{new_id}"),
            InlineKeyboardButton(text="Нет, это другой чек", callback_data=f"dupkeep:{new_id}"),
        ]
    ]
    if base := get_settings().web_base_url:
        rows.append([InlineKeyboardButton(text="🔎 Открыть записанный", url=f"{base}/receipts/{old_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
