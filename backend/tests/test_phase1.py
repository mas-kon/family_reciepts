"""Regression tests for the review fixes: access, SQLite locks, bank duplicates, restarts."""

import datetime as dt

import httpx
import pytest
from sqlalchemy import func, select

from app.api import auth
from app.bank import book_statement, external_ids, handle_bank_text
from app.config import Settings, get_settings
from app.db.models import LLMCall, Receipt
from app.db.seed import fail_interrupted
from app.llm.schema import ParsedBankTx, ParsedVoice, _to_float
from app.receipts.service import ReceiptService
from tests.conftest import LIDL, FakeLLM, receipt_image

BAD = {**LIDL, "items": LIDL["items"][:2]}  # sums do not add up -> needs_review


@pytest.fixture
async def client(session):
    from app.web import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c


# ---------- access ----------


def test_default_secret_key_is_replaced_by_a_persistent_random_one(tmp_path):
    a = Settings(secret_key="change-me", data_dir=tmp_path)
    b = Settings(secret_key="", data_dir=tmp_path)
    assert a.secret_key not in {"", "change-me"} and len(a.secret_key) >= 32
    assert a.secret_key == b.secret_key == (tmp_path / ".secret_key").read_text()
    assert Settings(secret_key="mine", data_dir=tmp_path).secret_key == "mine"


async def test_password_login_with_non_ascii_and_throttling(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_disabled", False)
    monkeypatch.setattr(s, "web_password", "пароль")
    auth._failures.clear()
    assert (await client.post("/api/auth/password", json={"password": "пароль"})).status_code == 200
    for _ in range(auth.MAX_FAILURES):
        assert (await client.post("/api/auth/password", json={"password": "не тот"})).status_code == 403
    assert (await client.post("/api/auth/password", json={"password": "пароль"})).status_code == 429
    auth._failures.clear()


def test_empty_allow_list_is_closed_outside_dev(monkeypatch):
    from app.bot.handlers import _allowed

    s = get_settings()
    monkeypatch.setattr(s, "allowed_chat_ids", "")
    monkeypatch.setattr(s, "auth_disabled", False)
    assert not _allowed(-100)
    monkeypatch.setattr(s, "auth_disabled", True)
    assert _allowed(-100)
    monkeypatch.setattr(s, "allowed_chat_ids", "-5")
    assert _allowed(-5) and not _allowed(-100)


async def test_health_checks_database_and_bot(client):
    assert (await client.get("/api/health")).status_code == 200

    class Dead:
        def done(self):
            return True

    client._transport.app.state.polling_task = Dead()
    assert (await client.get("/api/health")).status_code == 503


# ---------- members ----------


async def test_rename_survives_the_next_message(session):
    svc = ReceiptService(session, FakeLLM())
    u = await svc.get_or_create_user(7, "Anna K.", "anna")
    u.name = "Анна"  # renamed by hand in the web app
    await session.commit()
    again = await svc.get_or_create_user(7, "Anna K.", "anna_new")
    assert again.id == u.id and again.name == "Анна" and again.username == "anna_new"


# ---------- SQLite write lock during an LLM call ----------


class LoggingLLM(FakeLLM):
    """Like the real client, every request is written to the usage log."""

    async def parse_receipt(self, image, system, models=None, hint=None):
        from app.llm.usage import record_call

        res = self._next_receipt(models)
        await record_call("receipt", res.model, None)
        return res


async def test_cascade_second_request_is_logged(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_strong_models", "strong/model")
    llm = LoggingLLM([BAD, LIDL])
    r = (await ReceiptService(session, llm).process_photo(receipt_image(), None)).receipt
    assert r.status == "ok" and r.llm_model == "strong/model"
    # the usage row of the strong model needs the write lock: it must not be held by our session
    assert await session.scalar(select(func.count(LLMCall.id))) == 2


# ---------- bank duplicates ----------


def tx(day: int, amount=2.5, merchant="Billa", **kw) -> ParsedBankTx:
    return ParsedBankTx(date=dt.datetime(2026, 10, day, 10, 0), amount=amount, merchant=merchant, **kw)


async def test_same_purchase_on_consecutive_days_is_booked_twice(session):
    svc = ReceiptService(session, FakeLLM())
    booked, skipped = await book_statement(svc, [tx(10), tx(11), tx(12)], None)
    assert (len(booked), skipped) == (3, 0)


async def test_identical_operations_of_one_day_are_separate_and_reload_is_idempotent(session):
    svc = ReceiptService(session, FakeLLM())
    day = [tx(10), tx(10)]
    assert len(set(external_ids(day))) == 2
    booked, skipped = await book_statement(svc, day, None)
    assert (len(booked), skipped) == (2, 0)
    booked, skipped = await book_statement(svc, day, None)
    assert (len(booked), skipped) == (0, 2)


async def test_subset_of_a_statement_keeps_its_ids(session):
    svc = ReceiptService(session, FakeLLM())
    day = [tx(10), tx(10)]
    ids = external_ids(day)
    first, _ = await book_statement(svc, day[:1], None, ids=ids[:1])
    assert len(first) == 1
    # the preview showed the 2nd one as new; booking only it must not collide with the 1st
    booked, skipped = await book_statement(svc, day[1:], None, ids=ids[1:], batch_ids=set(ids))
    assert (len(booked), skipped) == (1, 0)


async def test_bank_row_still_matches_a_receipt_photo(session):
    svc = ReceiptService(session, FakeLLM(LIDL))
    photo = (await svc.process_photo(receipt_image(), None)).receipt  # 23.40 on 2026-01-15
    row = ParsedBankTx(date=dt.datetime(2026, 1, 16, 9, 0), amount=23.40, merchant="Lidl")
    booked, skipped = await book_statement(svc, [row], None)
    assert (len(booked), skipped) == (0, 1)
    assert await session.scalar(select(func.count(Receipt.id))) == 1 and photo.id


async def test_two_sms_of_the_same_amount_on_different_days_are_both_booked(session):
    for day in (10, 11):
        bank = {"transactions": [{"date": f"2026-10-{day}T10:00", "amount": 2.5, "merchant": "Costa"}]}
        results = await handle_bank_text(ReceiptService(session, FakeLLM(bank=bank)), "...", None)
        assert results[0].receipt is not None
    assert await session.scalar(select(func.count(Receipt.id))) == 2


# ---------- restarts ----------


async def test_interrupted_recognition_is_marked_failed(session):
    session.add(Receipt(source="photo", status="pending"))
    session.add(Receipt(source="photo", status="ok"))
    await session.commit()
    assert await fail_interrupted(session) == 1
    session.expunge_all()
    statuses = sorted(await session.scalars(select(Receipt.status)))
    assert statuses == ["failed", "ok"]


async def test_monthly_report_is_sent_after_a_missed_run(session, monkeypatch, tmp_path):
    from app import scheduler

    s = get_settings()
    monkeypatch.setattr(s, "data_dir", tmp_path)
    monkeypatch.setattr(s, "report_chat_id", -100)
    sent = []

    async def fake_send(bot, month=None):
        sent.append(month)
        scheduler._sent_marker(month).touch()

    monkeypatch.setattr(scheduler, "send_monthly_report", fake_send)
    await scheduler.catch_up_report(object())
    assert sent == []  # first start: nothing to catch up, the state is only recorded
    scheduler._sent_marker(scheduler.last_month()).unlink()
    await scheduler.catch_up_report(object())
    assert sent == [scheduler.last_month()]
    await scheduler.catch_up_report(object())
    assert len(sent) == 1


# ---------- parsing ----------


@pytest.mark.parametrize(
    "raw,expected",
    [("1,234.56", 1234.56), ("1.234,56", 1234.56), ("23,40 €", 23.4), ("1 234,5", 1234.5), ("-2.50", -2.5), (12, 12.0)],
)
def test_to_float_separators(raw, expected):
    assert _to_float(raw) == expected


def test_voice_without_flags_is_not_an_expense():
    v = ParsedVoice.model_validate({"transcript": "", "amount": 12})
    assert not v.has_speech and not v.is_expense


# ---------- API validation ----------


async def test_api_rejects_unknown_references_instead_of_500(client):
    r = await client.post("/api/receipts/manual", json={"amount": 5, "category_id": 9999})
    assert r.status_code == 400
    r = await client.post("/api/receipts/manual", json={"amount": 5, "user_id": 9999})
    assert r.status_code == 400
    cat = (await client.post("/api/categories", json={"name": "Новая"})).json()
    assert (await client.post("/api/categories", json={"name": "новая"})).status_code == 409
    assert cat["id"]
    assert (await client.post("/api/reports/send?month=2026-13")).status_code == 422
    rec = await client.post("/api/receipts/manual", json={"amount": 5})
    rid = rec.json()["id"]
    assert (await client.patch(f"/api/receipts/{rid}", json={"status": "bogus"})).status_code == 422


async def test_deleted_record_id_is_not_reused_and_image_is_revalidated(session, client):
    svc = ReceiptService(session, FakeLLM(LIDL))
    first = (await svc.process_photo(receipt_image(), None)).receipt
    first_id = first.id
    img = await client.get(f"/api/receipts/{first_id}/image")
    assert "no-cache" in img.headers["cache-control"] and img.headers.get("etag")
    await svc.delete_receipt(first)
    second = (await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)).receipt
    assert second.id != first_id  # old chat buttons and cached pictures must not point at the new record


async def test_same_purchase_from_a_screenshot_without_qr_is_a_duplicate(session):
    svc = ReceiptService(session, FakeLLM([LIDL, {**LIDL, "purchased_at": "2026-01-15T14:28"}]))
    first = await svc.process_photo(receipt_image("DT123456*0012345*2026-01-15*14:30:25*23.40"), None)
    again = await svc.process_photo(receipt_image(), None)  # the shop app's picture: no QR code
    assert again.duplicate_of.id == first.receipt.id
    assert await session.scalar(select(func.count(Receipt.id))) == 1

    other = {**LIDL, "purchased_at": "2026-01-15T18:00"}  # same total hours later: a different purchase
    third = await ReceiptService(session, FakeLLM(other)).process_photo(receipt_image(), None)
    assert third.receipt is not None and await session.scalar(select(func.count(Receipt.id))) == 2
