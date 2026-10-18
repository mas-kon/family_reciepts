import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="checkbot-test-"))
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp / 'test.db'}",
    DATA_DIR=str(_tmp / "data"),
    AUTH_DISABLED="true",
    BOT_TOKEN="",
    LLM_API_KEY="test",
    ALLOWED_CHAT_IDS="",
    # the developer's .env must not change model choices in tests
    LLM_STRONG_MODELS="",
    LLM_AUDIO_MODELS="",
    LLM_ASK_MODELS="",
    IMAP_HOST="",
)

from PIL import Image

from app.db import session as db_session
from app.db.models import Base
from app.db.seed import seed_categories
from app.llm.client import LLMError, LLMResult
from app.llm.schema import (
    ParsedBank,
    ParsedManual,
    ParsedProducts,
    ParsedReceipt,
    ParsedVoice,
)


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
    """Returns canned answers instead of calling a real model.

    receipt: one answer, or a list consumed in order (for the cascade: first the cheap model,
    then the strong one).
    """

    def __init__(
        self,
        receipt: dict | list | None = None,
        manual: dict | None = None,
        fail: bool = False,
        bank: dict | None = None,
        voice: dict | None = None,
        products: dict | None = None,
        comment: str | None = None,
        tool_script: list | None = None,
    ):
        self.receipt = receipt
        self.manual = manual
        self.fail = fail
        self.bank = bank
        self.voice = voice
        self.products = products or {}
        self.comment = comment
        self.tool_script = list(tool_script or [])
        self.calls = 0
        self.models_used: list = []
        self.hint = None
        self.texts: list[str] = []
        self.tool_messages: list = []

    def _next_receipt(self, models):
        self.calls += 1
        self.models_used.append(models)
        if self.fail:
            raise LLMError("all models failed")
        answer = self.receipt.pop(0) if isinstance(self.receipt, list) else self.receipt
        model = models[0] if models else "fake/model"
        return LLMResult(data=ParsedReceipt.model_validate(answer), model=model, raw=answer)

    async def parse_receipt(self, image, system, models=None, hint=None):
        self.hint = hint
        return self._next_receipt(models)

    async def parse_receipt_text(self, text, system, hint=None, models=None):
        self.hint = hint
        self.texts.append(text)
        return self._next_receipt(models)

    async def parse_manual(self, text, system):
        if self.fail or self.manual is None:
            raise LLMError("no")
        return LLMResult(data=ParsedManual.model_validate(self.manual), model="fake/model", raw=self.manual)

    async def parse_bank(self, text):
        if self.fail or self.bank is None:
            raise LLMError("no")
        return LLMResult(data=ParsedBank.model_validate(self.bank), model="fake/model", raw=self.bank)

    async def parse_voice(self, wav, system):
        if self.fail or self.voice is None:
            raise LLMError("no")
        self.voice_system = system
        return LLMResult(data=ParsedVoice.model_validate(self.voice), model="fake/model", raw=self.voice)

    async def group_products(self, names, known):
        data = {"products": {n: self.products[n] for n in names if n in self.products}}
        return LLMResult(data=ParsedProducts.model_validate(data), model="fake/model", raw=data)

    async def complete_text(self, messages, models):
        if self.comment is None:
            raise LLMError("no")
        return self.comment, "fake/model"

    async def chat_tools(self, messages, tools, models):
        """tool_script: list of ("call", name, args) or ("answer", text)."""
        self.tool_messages = messages
        step = self.tool_script.pop(0)
        if step[0] == "answer":
            return SimpleNamespace(content=step[1], tool_calls=None), "fake/model"
        call = SimpleNamespace(
            id=f"call{len(self.tool_script)}",
            function=SimpleNamespace(name=step[1], arguments=json.dumps(step[2], ensure_ascii=False)),
        )
        return SimpleNamespace(content="", tool_calls=[call]), "fake/model"


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
        {
            "name_original": "ПРЯСНО МЛЯКО 3% 1Л",
            "name_ru": "Молоко 3% 1 л",
            "qty": 2,
            "unit_price": 1.20,
            "total": 2.40,
            "category": "Продукты / Молочные продукты и яйца",
        },
        {
            "name_original": "БАНАНИ",
            "name_ru": "Бананы",
            "qty": 1.25,
            "unit_price": 1.60,
            "total": 2.00,
            "category": "Овощи и фрукты",
        },
        {
            "name_original": "ПРАХ ЗА ПРАНЕ",
            "name_ru": "Стиральный порошок",
            "qty": 1,
            "total": 20.00,
            "category": "Хозяйство / Бытовая химия",
        },
        {
            "name_original": "ОТСТЪПКА",
            "name_ru": "Скидка",
            "qty": 1,
            "total": -1.00,
            "category": "Хозяйство / Бытовая химия",
        },
    ],
}
