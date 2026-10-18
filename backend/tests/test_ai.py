"""AI features: cascade, warranty, e-mail/PDF receipts, bank, voice, products, questions, comments."""

import io
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Category, Item, ProductAlias, Receipt, User
from app.receipts.service import ReceiptService, add_months, now_local
from tests.conftest import LIDL, FakeLLM, receipt_image


async def cat_id(session, name):
    return await session.scalar(select(Category.id).where(Category.name == name))


BAD = {**LIDL, "items": LIDL["items"][:2]}  # sums do not add up -> needs_review


# ---------- cascade ----------


async def test_cascade_rereads_with_strong_model(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_strong_models", "strong/model")
    llm = FakeLLM([BAD, LIDL])
    r = (await ReceiptService(session, llm).process_photo(receipt_image(), None)).receipt
    assert llm.models_used == [None, ["strong/model"]]
    assert r.status == "ok" and r.llm_model == "strong/model"
    assert len(r.items) == 4


async def test_no_cascade_when_receipt_is_fine(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_strong_models", "strong/model")
    llm = FakeLLM(LIDL)
    await ReceiptService(session, llm).process_photo(receipt_image(), None)
    assert llm.calls == 1


async def test_cascade_keeps_review_note(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_strong_models", "strong/model")
    r = (await ReceiptService(session, FakeLLM([BAD, BAD])).process_photo(receipt_image(), None)).receipt
    assert r.status == "needs_review" and "перечитано моделью strong/model" in r.review_reason


# ---------- warranty ----------


def test_add_months():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 10, 16), 24) == date(2028, 10, 16)


async def test_warranty_from_receipt_and_reminder(session, monkeypatch):
    tv = {
        "is_receipt": True, "store": "Technopolis", "purchased_at": "2024-11-20T12:00", "total": 500,
        "items": [{"name_original": "TV SAMSUNG 55", "name_ru": "Телевизор", "total": 500,
                   "category": "Электроника", "warranty_months": 24}],
    }
    r = (await ReceiptService(session, FakeLLM(tv)).process_photo(receipt_image(), None)).receipt
    assert r.items[0].warranty_until == date(2026, 11, 20)

    from app import warranty

    due = await warranty.due_items(session, 40)
    assert [i.name_original for i, _ in due] == ["TV SAMSUNG 55"]

    class Bot:
        sent = []

        async def send_message(self, chat, text, **kw):
            self.sent.append(text)

    monkeypatch.setattr(get_settings(), "allowed_chat_ids", "-100")
    monkeypatch.setattr(get_settings(), "warranty_remind_days", 40)
    bot = Bot()
    assert await warranty.remind(bot) == 1
    assert "Телевизор" in bot.sent[0]
    assert await warranty.remind(bot) == 0  # only once


# ---------- e-mail and PDF receipts ----------


async def test_text_receipt_and_duplicate(session):
    llm = FakeLLM(LIDL)
    svc = ReceiptService(session, llm)
    r = (await svc.process_text_receipt("Ваш заказ: молоко 2.40 ...", None, external_id="email:<1@x>")).receipt
    assert r.source == "email" and r.status == "ok" and r.source_text.startswith("Ваш заказ")
    again = await svc.process_text_receipt("Ваш заказ", None, external_id="email:<1@x>")
    assert again.duplicate_of.id == r.id and llm.calls == 1
    # an e-mail receipt without a picture can be re-read from its text
    res = await svc.reprocess(r)
    assert res.receipt.status == "ok" and llm.calls == 2


def _pdf_with_text(text: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(4, 6))
    fig.text(0.05, 0.5, text, fontsize=8)
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf")
    plt.close(fig)
    return buf.getvalue()


async def test_pdf_receipt_uses_text_layer_and_keeps_picture(session):
    llm = FakeLLM(LIDL)
    pdf = _pdf_with_text("LIDL\nPRYASNO MLYAKO 2.40\nBANANI 2.00\nPRAH 20.00\nOTSTAPKA -1.00\nTOTAL 23.40 EUR")
    r = (await ReceiptService(session, llm).process_pdf(pdf, None)).receipt
    assert "TOTAL 23.40" in llm.texts[0]
    assert r.image_path and (get_settings().data_dir / r.image_path).exists()


def test_parse_mail_html_body():
    from app.email_inbox import parse_mail

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Ваш заказ в Glovo"
    msg["From"] = "Anna <Anna@Example.com>"
    msg["Message-ID"] = "<abc@glovo>"
    msg.attach(MIMEText("<html><style>x{}</style><table><tr><td>Пицца</td><td>12.50 €</td></tr></table></html>", "html"))
    m = parse_mail(msg.as_bytes())
    assert m.sender == "anna@example.com" and m.message_id == "<abc@glovo>"
    assert "Пицца | 12.50 €" in m.text and "x{}" not in m.text


async def test_mail_owner_by_address(session):
    from app.email_inbox import ParsedMail, process_mail

    session.add(User(name="Анна", emails="anna@example.com,anna.work@company.bg"))
    await session.commit()
    mail = ParsedMail(message_id="<m1>", sender="anna@example.com", subject="Заказ", text="Пицца 12.50")
    r = (await process_mail(ReceiptService(session, FakeLLM(LIDL)), mail)).receipt
    assert (await session.get(User, r.user_id)).name == "Анна" and r.external_id == "email:<m1>"
    # any of the person's addresses
    mail = ParsedMail(message_id="<m2>", sender="anna.work@company.bg", subject="Заказ", text="Кафе 4.20")
    r = (await process_mail(ReceiptService(session, FakeLLM(LIDL)), mail)).receipt
    assert (await session.get(User, r.user_id)).name == "Анна"


# ---------- bank ----------


def test_bank_message_detection():
    from app.bank import looks_like_bank_message

    assert looks_like_bank_message("Плащане с карта ****1234 за 12.50 EUR в LIDL BULGARIA")
    assert looks_like_bank_message("Покупка 3,50 € по карте *5678 COSTA COFFEE")
    assert not looks_like_bank_message("купи молоко и хлеб")
    assert not looks_like_bank_message("кофе стоил 3.50 €, дорого")


SMS = {"transactions": [{"date": "2026-10-16T17:17", "amount": 12.5, "merchant": "Kaufland", "card": "1234"}]}


async def test_bank_message_books_for_card_owner(session):
    from app.bank import handle_bank_text

    session.add(User(name="Маша", cards="1234"))
    await session.commit()
    svc = ReceiptService(session, FakeLLM(bank=SMS, manual={"name": "Kaufland", "amount": 12.5, "category": "Бакалея"}))
    [res] = await handle_bank_text(svc, "Плащане 12.50 EUR ...", None)
    r = res.receipt
    assert r.source == "bank" and r.total == 12.5 and (await session.get(User, r.user_id)).name == "Маша"
    assert r.items[0].category_id == await cat_id(session, "Бакалея")
    # the same SMS again is recognised, not booked twice
    [again] = await handle_bank_text(svc, "Плащане 12.50 EUR ...", None)
    assert again.receipt is None and again.match.id == r.id


async def test_bank_message_matches_existing_receipt(session):
    from app.bank import handle_bank_text

    svc = ReceiptService(session, FakeLLM(LIDL, bank={"transactions": [
        {"date": "2026-01-16T09:00", "amount": 23.40, "merchant": "Lidl"},
        {"date": "2026-01-16T09:00", "amount": 100, "merchant": "Salary", "is_expense": False},
    ]}))
    photo = (await svc.process_photo(receipt_image(), None)).receipt  # 23.40 on 2026-01-15
    results = await handle_bank_text(svc, "...", None)
    assert len(results) == 1 and results[0].match.id == photo.id
    assert await session.scalar(select(func.count(Receipt.id))) == 1


def test_statement_csv_is_normalised():
    from app.bank import statement_text

    csv_data = "Дата;Описание;Сума\n16.10.2026;LIDL SOFIA;-12,50\n\n17.10.2026;Заплата;1500,00\n".encode("cp1251")
    text = statement_text(csv_data, "statement.csv")
    assert "16.10.2026 | LIDL SOFIA | -12,50" in text


async def test_statement_analyse_and_import(client, session):
    from app.api import ai

    statement = {"transactions": [
        {"date": "2026-10-10T10:00", "amount": 7.2, "merchant": "Billa", "card": "9999"},
        {"date": "2026-01-15T14:00", "amount": 23.40, "merchant": "Lidl"},
    ]}
    await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)

    orig = ai.ReceiptService.__init__

    def init(self, s, llm=None, auto_products=True):
        orig(self, s, FakeLLM(bank=statement), auto_products=False)

    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(ai.ReceiptService, "__init__", init)
    try:
        r = await client.post("/api/bank/statement", files={"file": ("s.csv", b"x;y\n1;2\n", "text/csv")})
        rows = r.json()["transactions"]
        assert [x["match"] is not None for x in rows] == [False, True]
        imp = (await client.post("/api/bank/import", json={"transactions": [rows[0]]})).json()
        assert imp["booked"] == 1 and imp["skipped"] == 0 and imp["import_id"]
        again = await client.post("/api/bank/import", json={"transactions": [rows[0]]})
        assert again.json() == {"booked": 0, "skipped": 1, "import_id": None, "marked_transfers": 0}

        # the whole statement can be listed and deleted at once; other records stay
        imports = (await client.get("/api/bank/imports")).json()
        assert [(i["import_id"], i["count"]) for i in imports] == [(imp["import_id"], 1)]
        listed = (await client.get(f"/api/receipts?import_id={imp['import_id']}")).json()
        assert listed["total"] == 1 and listed["items"][0]["import_id"] == imp["import_id"]
        before = (await client.get("/api/receipts")).json()["total"]
        assert (await client.delete(f"/api/bank/imports/{imp['import_id']}")).json() == {"deleted": 1}
        assert (await client.get("/api/receipts")).json()["total"] == before - 1
        assert (await client.get("/api/bank/imports")).json() == []
    finally:
        mp.undo()


@pytest.fixture
async def client(session):
    import httpx

    from app.web import create_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c


# ---------- voice ----------


def _opus(seconds: float = 1.0) -> bytes:
    import av
    import numpy as np

    buf = io.BytesIO()
    out = av.open(buf, "w", format="ogg")
    st = out.add_stream("libopus", rate=48000)
    st.layout = "mono"
    n = int(48000 * seconds)
    fr = av.AudioFrame.from_ndarray((np.sin(np.linspace(0, 400, n)) * 8000).astype("int16").reshape(1, -1),
                                    format="s16", layout="mono")
    fr.sample_rate = 48000
    for p in st.encode(fr):
        out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


def test_voice_ogg_to_wav():
    from app.voice import to_wav

    wav = to_wav(_opus(1.0))
    assert wav[:4] == b"RIFF" and abs((len(wav) - 44) / 32000 - 1.0) < 0.1


async def test_voice_books_for_family_member(session):
    from app.voice import handle_voice

    session.add(User(name="Маша"))
    await session.commit()
    llm = FakeLLM(voice={"transcript": "Маше на кино пятнадцать", "who": "Маша", "name": "кино", "amount": 15},
                  manual={"name": "Кино", "amount": 15, "category": "Развлечения"})
    res = await handle_voice(ReceiptService(session, llm), b"wav", None)
    r = res.receipt
    assert r.source == "voice" and r.total == 15 and (await session.get(User, r.user_id)).name == "Маша"
    assert r.items[0].name_original == "Кино" and "Маша" in llm.voice_system

    no_amount = await handle_voice(ReceiptService(session, FakeLLM(voice={"transcript": "привет"})), b"wav", None)
    assert no_amount.receipt is None and no_amount.problem


# ---------- products ----------


async def test_product_grouping_merge_and_split(client, session):
    from app import products

    llm = FakeLLM([LIDL, {**LIDL, "items": [{**LIDL["items"][0], "name_original": "МЛЯКО ПРЯСНО 3% 1Л"}]}],
                  products={"прясно мляко 3% 1л": "Молоко 3% 1 л", "мляко прясно 3% 1л": "Молоко 3% 1 л"})
    svc = ReceiptService(session, llm, auto_products=False)
    await svc.process_photo(receipt_image(), None)
    await svc.process_photo(receipt_image(), None)

    assert await products.group_names(session, llm) == 2
    rows = (await client.get("/api/products", params={"q": "молоко"})).json()
    assert rows[0]["key"] == "Молоко 3% 1 л" and rows[0]["variants"] == 2 and rows[0]["count"] == 2
    prices = (await client.get("/api/products/prices", params={"key": "Молоко 3% 1 л"})).json()
    assert len(prices) == 2

    merged = await client.post("/api/products/merge", json={"keys": ["Молоко 3% 1 л", "банани"], "product": "Разное"})
    assert merged.json()["lines"] == 3
    await client.post("/api/products/split", json={"key": "Разное"})
    aliases = list(await session.scalars(select(ProductAlias).execution_options(populate_existing=True)))
    assert all(a.manual and a.product == a.name_normalized for a in aliases)
    # automatic grouping does not undo a manual split
    assert await products.group_names(session, llm) == 0


# ---------- questions ----------


async def test_ask_runs_tools_and_answers(session):
    from app.ask import answer

    await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)
    llm = FakeLLM(tool_script=[
        ("call", "search_purchases", {"query": "мляко"}),
        ("answer", "На молоко ушло 2.40 €."),
    ])
    res = await answer(session, "сколько ушло на молоко?", llm=llm)
    assert res["answer"] == "На молоко ушло 2.40 €." and res["tools"] == ["search_purchases"]
    tool_result = llm.tool_messages[-1]
    assert tool_result["role"] == "tool" and '"total": 2.4' in tool_result["content"]


async def test_ask_tool_errors_are_reported_to_model(session):
    from app.ask import answer

    llm = FakeLLM(tool_script=[("call", "get_summary", {"bogus": 1}), ("answer", "ok")])
    res = await answer(session, "?", llm=llm)
    assert res["answer"] == "ok" and '"error"' in llm.tool_messages[-1]["content"]


# ---------- monthly comment ----------


async def test_monthly_report_has_comment(session):
    from app.reports import build_monthly_report

    await ReceiptService(session, FakeLLM(fail=True)).book_single(
        name="Хлеб", amount=3, category_id=None, user_id=None, source="manual", purchased_at=now_local()
    )
    text, _ = await build_monthly_report(session, f"{now_local():%Y-%m}", llm=FakeLLM(comment="Потратили <мало>."))
    assert "💬 Потратили &lt;мало&gt;." in text
    text, _ = await build_monthly_report(session, f"{now_local():%Y-%m}", llm=FakeLLM())
    assert "💬" not in text  # no comment when the LLM is unavailable


async def test_warranty_api_and_item_edit(client, session):
    r = (await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)).receipt
    item = r.items[2]
    until = (now_local().date() + timedelta(days=100)).isoformat()
    await client.patch(f"/api/items/{item.id}", json={"warranty_until": until})
    rows = (await client.get("/api/warranties")).json()
    assert rows[0]["item_id"] == item.id and rows[0]["days_left"] == 100
    assert (await session.get(Item, item.id, populate_existing=True)).warranty_notified is False


async def test_voice_without_speech_or_expense_books_nothing(session):
    from app.voice import handle_voice

    for answer in (
        {"has_speech": False, "transcript": "", "amount": None},
        # a model that still invents an amount for small talk must not create a record
        {"has_speech": True, "is_expense": False, "transcript": "привет, как дела", "amount": 12},
    ):
        res = await handle_voice(ReceiptService(session, FakeLLM(voice=answer)), b"wav", None)
        assert res.receipt is None
    assert await session.scalar(select(func.count(Receipt.id))) == 0


# ---------- income and transfers inside the family ----------


async def test_family_transfer_is_not_spending(session, client):
    import datetime as dt

    vera = User(name="Вера")
    session.add(vera)
    await session.commit()
    svc = ReceiptService(session, FakeLLM(None))
    when = dt.datetime(2026, 10, 5, 12)
    await svc.book_single(name="Хлеб", amount=10, category_id=None, user_id=None, source="manual", purchased_at=when)
    t1 = await svc.book_single(name="Перевод: Vera Maslennikova", amount=4, category_id=None, user_id=None,
                               source="bank", purchased_at=when, counterparty="Vera Maslennikova")
    t2 = await svc.book_single(name="Перевод: Vera Maslennikova", amount=3, category_id=None, user_id=None,
                               source="bank", purchased_at=when, counterparty="Vera Maslennikova")
    sal = (await client.post("/api/receipts/manual", json={
        "name": "Зарплата", "amount": 1500, "kind": "income", "purchased_at": "2026-10-05T09:00:00"})).json()
    assert sal["kind"] == "income"

    period = "date_from=2026-10-01&date_to=2026-10-31"
    s = (await client.get(f"/api/stats/summary?{period}")).json()
    assert s["total"] == 17 and s["income"]["total"] == 1500

    # one record marked with "remember" marks every transfer to this name
    r = (await client.patch(f"/api/receipts/{t1.id}", json={"kind": "transfer", "peer_user_id": vera.id,
                                                           "remember_peer": True})).json()
    assert r["kind"] == "transfer" and r["peer_name"] == "Вера"
    session.expunge_all()
    assert (await session.get(Receipt, t2.id)).kind == "transfer"
    assert (await session.get(User, vera.id)).bank_names == "Vera Maslennikova"
    s = (await client.get(f"/api/stats/summary?{period}")).json()
    assert s["total"] == 10 and s["transfers_total"] == 7 and s["income"]["total"] == 1500
    month = next(m for m in (await client.get("/api/stats/monthly?months=24")).json() if m["month"] == "2026-10")
    assert month["total"] == 10 and month["income"] == 1500


# ---------- LLM usage and balance ----------


class _Usage:
    def __init__(self, d):
        self.d = d

    def model_dump(self):
        return self.d


class _Resp:
    def __init__(self, provider, cost, upstream, byok):
        self.provider = provider
        self.usage = _Usage({"prompt_tokens": 100, "completion_tokens": 20, "cost": cost, "is_byok": byok,
                             "cost_details": {"upstream_inference_cost": upstream}})


async def test_llm_usage_log_and_report(session, client):
    from app.llm.usage import record_call

    await record_call("receipt", "google/gemini-2.5-flash", _Resp("Google", 0.002, 0.002, False))
    await record_call("receipt", "google/gemini-2.5-flash", _Resp("Google AI Studio", 0.0, 0.003, True))
    await record_call("bank", "deepseek/deepseek-v4.1-flash", None, error=RuntimeError("429 rate limited"))

    r = (await client.get("/api/llm/usage?days=7")).json()
    assert r["total"]["calls"] == 3 and r["total"]["failed"] == 1
    assert round(r["total"]["cost"], 4) == 0.002 and round(r["total"]["byok_cost"], 4) == 0.003
    receipt = next(t for t in r["by_task"] if t["task"] == "receipt")
    assert receipt["label"] == "Чеки по фото" and receipt["calls"] == 2 and receipt["byok_calls"] == 1
    assert {m["provider"] for m in r["by_model"]} == {"Google", "Google AI Studio", None}


async def test_low_balance_warns_once(monkeypatch):
    from app.llm import usage

    class Bot:
        sent: list = []

        async def send_message(self, chat, text):
            self.sent.append(text)

    state = {"balance": 0.4}

    async def fake_balances(fresh=False):
        return [{"provider": "OpenRouter", "currency": "USD", "balance": state["balance"],
                 "key": {"limit": 5, "limit_remaining": 4.9}}]

    monkeypatch.setattr(usage, "balances", fake_balances)
    monkeypatch.setattr(get_settings(), "report_chat_id", -100)
    bot = Bot()
    assert await usage.check_balance(bot) == ["OpenRouter: на счёте осталось 0.40$"]
    assert await usage.check_balance(bot) == []  # already warned
    state["balance"] = 7
    assert await usage.check_balance(bot) == []
    state["balance"] = 0.2  # topped up and spent again: warns again
    assert len(await usage.check_balance(bot)) == 1 and len(bot.sent) == 2
