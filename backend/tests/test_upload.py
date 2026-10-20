"""POST /api/receipts/upload and the web app manifest."""

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import Receipt, User
from app.web import create_app
from tests.conftest import LIDL, FakeLLM, receipt_image


@pytest.fixture
async def client(session):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c


@pytest.fixture
def llm(monkeypatch):
    def use(fake: FakeLLM) -> FakeLLM:
        monkeypatch.setattr("app.receipts.base.get_llm", lambda: fake)
        return fake

    return use


def upload(
    client, data=None, name="r.jpg", mime="image/jpeg", client_id="11111111-aaaa-bbbb-cccc-000000000001", **form
):
    return client.post(
        "/api/receipts/upload",
        files={"file": (name, data if data is not None else receipt_image(), mime)},
        data={"client_id": client_id, **form},
    )


async def count(session) -> int:
    return await session.scalar(select(func.count()).select_from(Receipt)) or 0


async def test_upload_photo_creates_record(client, session, llm):
    llm(FakeLLM(LIDL))
    user = User(telegram_id=1, name="Маша")
    session.add(user)
    await session.commit()
    r = await upload(client, user_id=str(user.id), note="к празднику")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ok" and body["alerts"] == []
    assert body["receipt"]["user_id"] == user.id
    assert body["receipt"]["note"] == "к празднику"
    assert len(body["receipt"]["items"]) == 4
    assert await count(session) == 1


async def test_repeated_client_id_is_a_duplicate(client, session, llm):
    fake = llm(FakeLLM(LIDL))
    first = (await upload(client)).json()
    again = (await upload(client)).json()
    assert again["status"] == "duplicate" and again["receipt"] is None
    assert again["duplicate_of"]["id"] == first["receipt"]["id"]
    assert await count(session) == 1 and fake.calls == 1


async def test_not_a_receipt_saves_nothing(client, session, llm):
    llm(FakeLLM({"is_receipt": False}))
    body = (await upload(client)).json()
    assert body["status"] == "not_receipt" and body["receipt"] is None
    assert await count(session) == 0


async def test_llm_failure_keeps_record_for_retry(client, session, llm):
    llm(FakeLLM(fail=True))
    body = (await upload(client)).json()
    assert body["status"] == "failed"
    assert body["receipt"]["status"] == "failed"
    assert await count(session) == 1


async def test_too_big_file_is_rejected(client, session, llm, monkeypatch):
    llm(FakeLLM(LIDL))
    monkeypatch.setattr("app.api.receipts.MAX_PHOTO_BYTES", 100)
    r = await upload(client)
    assert r.status_code == 413
    assert await count(session) == 0


async def test_pdf_statement_is_not_booked(client, session, llm, monkeypatch):
    fake = llm(FakeLLM(LIDL))
    monkeypatch.setattr("app.api.receipts.statement_text", lambda data, name: "stmt")
    monkeypatch.setattr("app.api.receipts.looks_like_statement", lambda text: True)
    body = (await upload(client, b"%PDF-1.4", name="s.pdf", mime="application/pdf")).json()
    assert body["status"] == "statement" and body["receipt"] is None
    assert await count(session) == 0 and fake.calls == 0


async def test_client_id_is_validated(client):
    r = await upload(client, client_id="x")
    assert r.status_code == 422


async def test_manifest(client, session):
    r = await client.get("/manifest.webmanifest")
    assert r.headers["content-type"].startswith("application/manifest+json")
    m = r.json()
    assert m["name"] == "Семейные расходы" and m["display"] == "standalone"
    assert m["share_target"]["action"] == "/share-target"
    assert m["share_target"]["params"]["files"][0]["name"] == "receipt"

    from app.i18n import set_language

    await set_language(session, "en")
    try:
        assert (await client.get("/manifest.webmanifest")).json()["name"] == "Family expenses"
    finally:
        await set_language(session, "ru")


async def test_share_target_without_service_worker_redirects(client):
    r = await client.post("/share-target", files={"receipt": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 303 and r.headers["location"] == "/receipts"
