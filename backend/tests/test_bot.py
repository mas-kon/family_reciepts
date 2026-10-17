"""Runs real aiogram handlers against a fake Telegram API session."""

import datetime as dt

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, GetFile, SendMessage
from aiogram.types import Chat, File, Message, Update
from sqlalchemy import func, select

from app.bot import handlers
from app.db.models import Receipt
from tests.conftest import LIDL, FakeLLM, receipt_image

CHAT = Chat(id=-100, type="group", title="Семья")


class FakeSession(BaseSession):
    def __init__(self, photo: bytes):
        super().__init__()
        self.photo = photo
        self.sent: list = []
        self._mid = 1000

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="photos/x.jpg")
        if isinstance(method, (SendMessage, EditMessageText)):
            self._mid += 1
            return Message(message_id=self._mid, date=dt.datetime.now(), chat=CHAT, text=method.text).as_(bot)
        return True

    async def stream_content(self, url, headers=None, timeout=30, chunk_size=65536, raise_for_status=True):
        yield self.photo

    async def close(self):
        pass

    def texts(self):
        return [m.text for m in self.sent if isinstance(m, (SendMessage, EditMessageText))]


def photo_update(uid: int = 1):
    return Update.model_validate(
        {
            "update_id": uid,
            "message": {
                "message_id": uid,
                "date": int(dt.datetime.now().timestamp()),
                "chat": {"id": CHAT.id, "type": "group", "title": "Семья"},
                "from": {"id": 7, "is_bot": False, "first_name": "Анна"},
                "photo": [{"file_id": "f1", "file_unique_id": "u1", "width": 600, "height": 900}],
            },
        }
    )


@pytest.fixture
def dp():
    d = Dispatcher()
    d.include_router(handlers.router)
    yield d
    d.sub_routers.clear()
    handlers.router._parent_router = None


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM(LIDL)
    orig = handlers.ReceiptService.__init__

    def init(self, session, _llm=None):
        orig(self, session, llm)

    monkeypatch.setattr(handlers.ReceiptService, "__init__", init)
    return llm


async def test_photo_in_group_is_recorded(session, fake_llm, dp):
    fs = FakeSession(receipt_image("DT123456*0012345*2026-01-15*14:30:25*23.40"))
    bot = Bot("42:TEST", session=fs, default=DefaultBotProperties(parse_mode="HTML"))

    await dp.feed_update(bot, photo_update(1))
    texts = fs.texts()
    assert texts[0].startswith("⏳")
    assert "Lidl" in texts[-1] and "23.40" in texts[-1]
    assert await session.scalar(select(func.count(Receipt.id))) == 1

    # same receipt again -> duplicate
    await dp.feed_update(bot, photo_update(2))
    assert "уже записан" in fs.texts()[-1]
    assert await session.scalar(select(func.count(Receipt.id))) == 1


def text_update(uid: int, text: str, reply_to: int | None = None):
    msg = {
        "message_id": uid,
        "date": int(dt.datetime.now().timestamp()),
        "chat": {"id": CHAT.id, "type": "group", "title": "Семья"},
        "from": {"id": 7, "is_bot": False, "first_name": "Анна"},
        "text": text,
    }
    if reply_to:
        msg["reply_to_message"] = {
            "message_id": reply_to,
            "date": int(dt.datetime.now().timestamp()),
            "chat": {"id": CHAT.id, "type": "group", "title": "Семья"},
            "text": "…",
        }
    return Update.model_validate({"update_id": uid, "message": msg})


async def test_manual_for_member_and_reply_edits(session, fake_llm, dp):
    from app.db.models import User

    fake_llm.manual = {"name": "Кино", "amount": 12, "category": "Развлечения"}
    session.add(User(name="Маша"))
    await session.commit()

    fs = FakeSession(b"")
    bot = Bot("42:TEST", session=fs, default=DefaultBotProperties(parse_mode="HTML"))

    await dp.feed_update(bot, text_update(10, "+ Маша: 12"))
    assert "Маша" in fs.texts()[-1] and "12.00" in fs.texts()[-1]
    bot_msg_id = fs._mid  # the bot's reply

    r = await session.scalar(select(Receipt).execution_options(populate_existing=True))
    assert r.user.name == "Маша" and r.bot_message_id == bot_msg_id
    assert r.items[0].category_id is None

    # reply with a description -> becomes the name, gets a category
    await dp.feed_update(bot, text_update(11, "кино", reply_to=bot_msg_id))
    # reply with a number -> new amount
    await dp.feed_update(bot, text_update(12, "13,50", reply_to=bot_msg_id))
    r = await session.scalar(select(Receipt).execution_options(populate_existing=True))
    assert r.note == "кино" and r.total == 13.5 and r.items[0].total == 13.5
    assert r.items[0].category_id is not None
    assert "13.50" in fs.texts()[-1]

    # unknown member is refused, nothing booked
    await dp.feed_update(bot, text_update(13, "+ Петя: 5"))
    assert "Не знаю" in fs.texts()[-1]
    assert await session.scalar(select(func.count(Receipt.id))) == 1

    # a reply to an unrelated message is ignored
    n = len(fs.sent)
    await dp.feed_update(bot, text_update(14, "ок", reply_to=999))
    assert len(fs.sent) == n
