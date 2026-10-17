import hashlib
import hmac
import time

import httpx
import pytest
from sqlalchemy import select

from app.api.auth import TelegramAuth, verify_telegram
from app.config import get_settings
from app.db.models import Category
from app.receipts.service import ReceiptService
from app.web import create_app
from tests.conftest import LIDL, FakeLLM, receipt_image


@pytest.fixture
async def client(session):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_receipt_flow(client, session):
    res = await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)
    rid = res.receipt.id

    lst = (await client.get("/api/receipts", params={"q": "мляко"})).json()
    assert lst["total"] == 1 and lst["items"][0]["has_image"]

    detail = (await client.get(f"/api/receipts/{rid}")).json()
    assert detail["items_sum"] == 23.40
    assert (await client.get(f"/api/receipts/{rid}/image")).status_code == 200

    sweets = await session.scalar(select(Category.id).where(Category.name == "Сладости и снеки"))
    item_id = detail["items"][1]["id"]
    patched = (await client.patch(f"/api/items/{item_id}", json={"category_id": sweets})).json()
    assert patched["items"][1]["category_id"] == sweets

    # the choice is remembered for the next receipt
    res2 = await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)
    assert res2.receipt.items[1].category_id == sweets

    summary = (await client.get("/api/stats/summary")).json()
    assert summary["receipts"] == 2 and summary["total"] == 46.80

    products = (await client.get("/api/products")).json()
    assert products[0]["count"] == 2
    prices = (await client.get("/api/products/prices", params={"name": products[0]["name_normalized"]})).json()
    assert len(prices) == 2

    csv = await client.get("/api/export.csv")
    assert "ПРЯСНО МЛЯКО" in csv.text

    assert (await client.delete(f"/api/receipts/{rid}")).json() == {"ok": True}
    assert (await client.get(f"/api/receipts/{rid}")).status_code == 404


async def test_auth_required(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_disabled", False)
    assert (await client.get("/api/receipts")).status_code == 401
    monkeypatch.setattr(get_settings(), "web_password", "secret")
    assert (await client.post("/api/auth/password", json={"password": "wrong"})).status_code == 403
    ok = await client.post("/api/auth/password", json={"password": "secret"})
    assert ok.status_code == 200
    assert (await client.get("/api/receipts")).status_code == 200


def test_verify_telegram_signature():
    token = "123:ABC"
    fields = {"id": 42, "first_name": "Ann", "auth_date": int(time.time())}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    h = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    assert verify_telegram(TelegramAuth(**fields, hash=h), token)
    assert not verify_telegram(TelegramAuth(**fields, hash="0" * 64), token)


def _signed(token: str, **fields) -> dict:
    fields = {k: str(v) for k, v in fields.items()}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    fields["hash"] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    return fields


async def test_telegram_redirect_login(client, session, monkeypatch):
    from app.db.models import User

    s = get_settings()
    monkeypatch.setattr(s, "auth_disabled", False)
    monkeypatch.setattr(s, "bot_token", "123:ABC")
    session.add(User(telegram_id=42, name="Анна"))  # known family member (no bot in tests)
    await session.commit()

    good = _signed("123:ABC", id=42, first_name="Ann", auth_date=int(time.time()), new_field="x")
    r = await client.get("/api/auth/telegram/callback", params=good)
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = await client.get("/api/auth/me")
    assert me.json()["name"] == "Анна"

    client.cookies.clear()
    bad = {**good, "hash": "0" * 64}
    r = await client.get("/api/auth/telegram/callback", params=bad)
    assert r.status_code == 303 and "login_error" in r.headers["location"]
    assert (await client.get("/api/auth/me")).status_code == 401

    stranger = _signed("123:ABC", id=99, first_name="X", auth_date=int(time.time()))
    r = await client.get("/api/auth/telegram/callback", params=stranger)
    assert "login_error" in r.headers["location"]


async def test_members_and_no_category(client, session):
    m = (await client.post("/api/users", json={"name": "Маша"})).json()
    assert m["has_telegram"] is False
    r = (await client.post("/api/receipts/manual", json={"amount": 9.5, "user_id": m["id"]})).json()
    assert r["items"][0]["name_original"] == "Без описания" and r["user_name"] == "Маша"

    lst = (await client.get("/api/receipts", params={"category_id": "none"})).json()
    assert lst["total"] == 1

    assert (await client.delete(f"/api/users/{m['id']}")).status_code == 409
    assert (await client.patch(f"/api/users/{m['id']}", json={"name": "Мария"})).json()["name"] == "Мария"
