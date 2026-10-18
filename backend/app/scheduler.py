"""Background jobs: monthly report on the 1st, daily booking of recurring payments."""

import calendar
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Recurring
from app.db.session import session_factory
from app.receipts.service import ReceiptService, now_local
from app.reports import build_monthly_report, last_month
from app.stats import new_budget_alerts

log = logging.getLogger(__name__)


async def send_monthly_report(bot: Bot | None, month: str | None = None) -> None:
    chat = get_settings().notify_chat_id
    if not bot or not chat:
        log.info("monthly report skipped: no bot or chat")
        return
    month = month or last_month()
    async with session_factory()() as session:
        text, chart = await build_monthly_report(session, month)
    if chart and len(text) <= 1024:
        await bot.send_photo(chat, BufferedInputFile(chart, f"report-{month}.png"), caption=text)
    elif chart:
        # a long report (with the comment) does not fit into a photo caption
        await bot.send_photo(chat, BufferedInputFile(chart, f"report-{month}.png"))
        await bot.send_message(chat, text)
    else:
        await bot.send_message(chat, text + "\n\nТрат за месяц нет.")


def _due_day(day_of_month: int, today: datetime) -> int:
    """Day 31 in a 30-day month books on the 30th."""
    return min(day_of_month, calendar.monthrange(today.year, today.month)[1])


async def book_recurring(bot: Bot | None) -> int:
    today = now_local()
    month = f"{today:%Y-%m}"
    booked = 0
    async with session_factory()() as session:
        items = list(await session.scalars(select(Recurring).where(Recurring.active.is_(True))))
        svc = ReceiptService(session)
        for rec in items:
            if rec.last_booked_month == month or today.day < _due_day(rec.day_of_month, today):
                continue
            receipt = await svc.book_single(
                name=rec.name,
                amount=rec.amount,
                category_id=rec.category_id,
                user_id=rec.user_id,
                source="recurring",
                kind=rec.kind,
                purchased_at=today.replace(day=_due_day(rec.day_of_month, today), hour=12, minute=0, second=0),
                note="Регулярное поступление" if rec.kind == "income" else "Регулярный платёж",
            )
            rec.last_booked_month = month
            await session.commit()
            booked += 1
            chat = get_settings().notify_chat_id
            if bot and chat:
                what = "регулярное поступление" if rec.kind == "income" else "регулярный платёж"
                await bot.send_message(chat, f"🔁 Записан {what}: {rec.name}, {rec.amount:.2f} €")
                for a in await new_budget_alerts(session, receipt):
                    await bot.send_message(chat, a)
    return booked


def create_scheduler(bot: Bot | None) -> AsyncIOScheduler:
    tz = get_settings().timezone
    sched = AsyncIOScheduler(timezone=tz)
    sched.add_job(send_monthly_report, CronTrigger(day=1, hour=9, minute=0, timezone=tz), args=[bot])
    sched.add_job(book_recurring, CronTrigger(hour=8, minute=0, timezone=tz), args=[bot])
    # catch up on missed recurring payments right after start
    sched.add_job(book_recurring, args=[bot], next_run_time=datetime.now(ZoneInfo(tz)))

    from app.llm.usage import check_balance
    from app.warranty import remind

    sched.add_job(check_balance, CronTrigger(hour=9, minute=30, timezone=tz), args=[bot])

    sched.add_job(remind, CronTrigger(hour=10, minute=0, timezone=tz), args=[bot])

    s = get_settings()
    if s.imap_host:
        from app.email_inbox import poll_inbox

        sched.add_job(
            poll_inbox, "interval", minutes=max(1, s.imap_poll_minutes), args=[bot],
            next_run_time=datetime.now(ZoneInfo(tz)), max_instances=1, coalesce=True,
        )
    return sched
