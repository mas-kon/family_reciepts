import io
import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="checkbot-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp / 'test.db'}",
    DATA_DIR=str(_tmp / "data"),
    AUTH_DISABLED="true",
    BOT_TOKEN="",
    LLM_API_KEY="test",
    ALLOWED_CHAT_IDS="",
)

from PIL import Image  # noqa: E402

from app.db import session as db_session  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.seed import seed_categories  # noqa: E402
from app.llm.client import LLMError, LLMResult  # noqa: E402
from app.llm.schema import ParsedManual, ParsedReceipt  # noqa: E402


@pytest.fixture
async def session():
    (_tmp / "test.db").unlink(missing_ok=True)
    engine = db_session.init_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db_session.session_factory()() as s:
        await seed_categories(s)
        yield s
    await engine.dispose()


class FakeLLM:
    """Returns canned answers instead of calling a real model."""

    def __init__(self, receipt: dict | None = None, manual: dict | None = None, fail: bool = False):
        self.receipt = receipt
        self.manual = manual
        self.fail = fail
        self.calls = 0

    async def parse_receipt(self, image, system, models=None, hint=None):
        self.hint = hint
        self.calls += 1
        if self.fail:
            raise LLMError("all models failed")
        return LLMResult(data=ParsedReceipt.model_validate(self.receipt), model="fake/model", raw=self.receipt)

    async def parse_manual(self, text, system):
        if self.fail or self.manual is None:
            raise LLMError("no")
        return LLMResult(data=ParsedManual.model_validate(self.manual), model="fake/model", raw=self.manual)


def receipt_image(qr_text: str | None = None) -> bytes:
    import zxingcpp

    canvas = Image.new("RGB", (600, 900), "white")
    if qr_text:
        qr = zxingcpp.create_barcode(qr_text, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6)
        canvas.paste(Image.fromarray(__import__("numpy").array(qr)), (150, 550))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


LIDL = {
    "is_receipt": True,
    "store": "Lidl",
    "purchased_at": "2026-01-15T14:30",
    "total": 23.40,
    "items": [
        {"name_original": "ПРЯСНО МЛЯКО 3% 1Л", "name_ru": "Молоко 3% 1 л", "qty": 2, "unit_price": 1.20,
         "total": 2.40, "category": "Продукты / Молочные продукты и яйца"},
        {"name_original": "БАНАНИ", "name_ru": "Бананы", "qty": 1.25, "unit_price": 1.60,
         "total": 2.00, "category": "Овощи и фрукты"},
        {"name_original": "ПРАХ ЗА ПРАНЕ", "name_ru": "Стиральный порошок", "qty": 1,
         "total": 20.00, "category": "Хозяйство / Бытовая химия"},
        {"name_original": "ОТСТЪПКА", "name_ru": "Скидка", "qty": 1,
         "total": -1.00, "category": "Хозяйство / Бытовая химия"},
    ],
}
