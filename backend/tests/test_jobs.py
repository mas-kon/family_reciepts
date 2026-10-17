from sqlalchemy import func, select

from app.db.models import Receipt, Recurring
from app.receipts.service import ReceiptService, now_local
from app.reports import build_monthly_report
from app.scheduler import book_recurring
from tests.conftest import FakeLLM


async def test_monthly_report_renders_png(session):
    svc = ReceiptService(session, FakeLLM(fail=True))
    await svc.book_single(name="Хлеб", amount=3, category_id=5, user_id=None,
                          source="manual", purchased_at=now_local())
    text, png = await build_monthly_report(session, f"{now_local():%Y-%m}")
    assert "3.00 €" in text
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


async def test_recurring_booked_once_per_month(session):
    session.add(Recurring(name="Интернет", amount=20, day_of_month=1))
    session.add(Recurring(name="Будущее", amount=5, day_of_month=31, active=False))
    await session.commit()
    assert await book_recurring(None) == 1
    assert await book_recurring(None) == 0
    count = await session.scalar(select(func.count(Receipt.id)).where(Receipt.source == "recurring"))
    assert count == 1
