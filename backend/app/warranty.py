"""Warranty tracking: items with warranty_until get a reminder in the group before it ends."""

import html
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.ui import receipt_keyboard
from app.clock import now_local
from app.config import get_settings
from app.db.models import Item, Receipt
from app.db.session import session_factory
from app.i18n import t

log = logging.getLogger(__name__)


async def due_items(session: AsyncSession, days: int) -> list[tuple[Item, Receipt]]:
    today = now_local().date()
    rows = await session.execute(
        select(Item, Receipt)
        .join(Receipt, Item.receipt_id == Receipt.id)
        .where(
            Item.warranty_until.is_not(None),
            Item.warranty_until >= today,
            Item.warranty_until <= today + timedelta(days=days),
            Item.warranty_notified.is_(False),
        )
        .order_by(Item.warranty_until)
    )
    return [(item, receipt) for item, receipt in rows]


async def remind(bot) -> int:
    s = get_settings()
    chat = s.notify_chat_id
    sent = 0
    if not (bot and chat):
        return 0
    async with session_factory()() as session:
        for item, receipt in await due_items(session, s.warranty_remind_days):
            bought = f"{receipt.purchased_at:%d.%m.%Y}" if receipt.purchased_at else "—"
            text = t(
                "warranty.reminder",
                date=f"{item.warranty_until:%d.%m.%Y}",
                name=html.escape(item.name_ru or item.name_original),
                bought=bought,
                store=", " + html.escape(receipt.store) if receipt.store else "",
            )
            await bot.send_message(chat, text, reply_markup=receipt_keyboard(receipt.id))
            sent += 1
            item.warranty_notified = True
            await session.commit()
    return sent
