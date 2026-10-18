from sqlalchemy import select

from app.db.models import Budget, Category, CategoryOverride, Receipt
from app.receipts.service import ReceiptService
from app.stats import new_budget_alerts, summary
from tests.conftest import LIDL, FakeLLM, receipt_image

QR = "DT123456*0012345*2026-01-15*14:30:25*23.40"


async def cat_id(session, name):
    return await session.scalar(select(Category.id).where(Category.name == name))


async def test_photo_with_qr_is_saved_and_checked(session):
    svc = ReceiptService(session, FakeLLM(LIDL))
    res = await svc.process_photo(receipt_image(QR), None)
    r = res.receipt
    assert r.status == "ok", r.review_reason
    assert r.fiscal_key == "DT123456:12345:20260115"
    assert r.total == 23.40
    assert len(r.items) == 4
    assert r.items[0].category_id == await cat_id(session, "Молочные продукты и яйца")
    # matched by leaf name alone
    assert r.items[1].category_id == await cat_id(session, "Овощи и фрукты")
    assert (svc.settings.data_dir / r.image_path).exists()


async def test_duplicate_receipt_is_rejected(session):
    llm = FakeLLM(LIDL)
    svc = ReceiptService(session, llm)
    first = await svc.process_photo(receipt_image(QR), None)
    second = await svc.process_photo(receipt_image(QR), None)
    assert second.duplicate_of.id == first.receipt.id
    assert llm.calls == 1


async def test_total_mismatch_needs_review(session):
    bad = {**LIDL, "items": LIDL["items"][:2]}
    res = await ReceiptService(session, FakeLLM(bad)).process_photo(receipt_image(), None)
    assert res.receipt.status == "needs_review"
    assert "не совпадает" in res.receipt.review_reason


async def test_qr_amount_mismatch_needs_review(session):
    res = await ReceiptService(session, FakeLLM(LIDL)).process_photo(
        receipt_image("DT123456*0012346*2026-01-15*14:30:25*30.00"), None
    )
    assert res.receipt.status == "needs_review"
    assert "QR" in res.receipt.review_reason


async def test_not_a_receipt_is_dropped(session):
    res = await ReceiptService(session, FakeLLM({"is_receipt": False})).process_photo(receipt_image(), None)
    assert res.not_receipt and res.receipt is None
    assert await session.scalar(select(Receipt.id)) is None


async def test_llm_failure_keeps_photo_for_retry(session):
    svc = ReceiptService(session, FakeLLM(fail=True))
    res = await svc.process_photo(receipt_image(), None)
    assert res.error
    assert res.receipt.status == "failed"
    svc.llm = FakeLLM(LIDL)
    again = await svc.reprocess(res.receipt)
    assert again.receipt.status in {"ok", "needs_review"}
    assert len(again.receipt.items) == 4


async def test_override_beats_llm_category(session):
    other = await cat_id(session, "Сладости и снеки")
    session.add(CategoryOverride(name_normalized="банани", category_id=other))
    await session.commit()
    res = await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)
    bananas = next(i for i in res.receipt.items if i.name_original == "БАНАНИ")
    assert bananas.category_id == other


async def test_remember_category_applies_to_existing(session):
    svc = ReceiptService(session, FakeLLM(LIDL))
    await svc.process_photo(receipt_image(), None)
    await svc.process_photo(receipt_image(), None)
    target = await cat_id(session, "Прочее")
    await svc.remember_category("банани", target, apply_existing=True)
    await session.commit()
    receipts = (await session.scalars(select(Receipt).execution_options(populate_existing=True))).all()
    for r in receipts:
        assert next(i for i in r.items if i.name_normalized == "банани").category_id == target


async def test_manual_text_entry(session):
    svc = ReceiptService(
        session, FakeLLM(manual={"name": "Такси", "amount": 12, "category": "Такси и общественный транспорт"})
    )
    r = await svc.add_manual_text("такси 12", None)
    assert r.source == "manual" and r.total == 12
    assert r.items[0].category_id == await cat_id(session, "Такси и общественный транспорт")


async def test_manual_text_works_without_llm(session):
    r = await ReceiptService(session, FakeLLM(fail=True)).add_manual_text("кофе 5", None)
    assert r.total == 5
    assert r.items[0].category_id == await cat_id(session, "Прочее")


async def test_summary_and_budget_alerts(session):
    from app.clock import now_local

    svc = ReceiptService(session, FakeLLM(fail=True))
    food = await cat_id(session, "Продукты")
    fruit = await cat_id(session, "Овощи и фрукты")
    session.add(Budget(category_id=food, amount=100))
    await session.commit()

    r1 = await svc.book_single(
        name="Яблоки", amount=85, category_id=fruit, user_id=None, source="manual", purchased_at=now_local()
    )
    alerts = await new_budget_alerts(session, r1)
    assert len(alerts) == 1 and "85%" in alerts[0]
    assert await new_budget_alerts(session, r1) == []

    r2 = await svc.book_single(
        name="Груши", amount=20, category_id=fruit, user_id=None, source="manual", purchased_at=now_local()
    )
    alerts = await new_budget_alerts(session, r2)
    assert len(alerts) == 1 and "превышен" in alerts[0]

    s = await summary(session, None, None)
    assert s["total"] == 105
    assert s["by_category"][0]["name"] == "Продукты"


REAL = {
    "is_receipt": True,
    "store": "Лидл България",
    "purchased_at": "2026-10-16T17:17",
    "total": 2.57,
    "items": [
        {
            "name_original": "CHUPA CHUPS THE BEST",
            "name_ru": "Чупа-чупс",
            "total": 0.28,
            "category": "Продукты / Сладости и снеки",
        },
        {
            "name_original": "СЛАДОЛЕД ВАНИЛ-ВИШНА",
            "name_ru": "Мороженое ваниль-вишня",
            "total": 2.29,
            "category": "Продукты / Сладости и снеки",
        },
    ],
}


async def test_real_receipt_sideways_is_straightened(session):
    from io import BytesIO
    from pathlib import Path

    from PIL import Image

    upright = Image.open(Path(__file__).parent / "fixtures" / "lidl_receipt.jpg")
    buf = BytesIO()
    upright.rotate(90, expand=True).save(buf, format="JPEG")  # as if shot sideways

    svc = ReceiptService(session, FakeLLM(REAL))
    r = (await svc.process_photo(buf.getvalue(), None)).receipt
    assert r.status == "ok", r.review_reason
    assert r.fiscal_key == "51019521:318288:20261016"
    assert r.purchased_at.strftime("%Y-%m-%d %H:%M:%S") == "2026-10-16 17:17:13"
    saved = Image.open(svc.settings.data_dir / r.image_path)
    assert saved.height > saved.width  # stored upright


async def test_amount_only_goes_without_category(session):
    llm = FakeLLM(manual={"name": "X", "amount": 1, "category": "Прочее"})
    r = await ReceiptService(session, llm).add_manual_text("12,50", None)
    assert r.total == 12.5
    assert r.items[0].name_original == "Без описания"
    assert r.items[0].category_id is None


async def test_description_names_and_classifies_bare_amount(session):
    llm = FakeLLM(manual={"name": "Кино", "amount": 12, "category": "Развлечения"})
    svc = ReceiptService(session, llm)
    r = await svc.add_manual_text("12", None)
    await svc.set_description(r, "кино с друзьями")
    assert r.note == "кино с друзьями"
    assert r.items[0].name_original == "кино с друзьями"
    assert r.items[0].category_id == await cat_id(session, "Развлечения")


async def test_description_does_not_rename_multi_item_receipt(session):
    svc = ReceiptService(session, FakeLLM(LIDL))
    r = (await svc.process_photo(receipt_image(), None)).receipt
    await svc.set_description(r, "к празднику")
    assert r.note == "к празднику"
    assert r.items[0].name_original == "ПРЯСНО МЛЯКО 3% 1Л"


async def test_total_only_receipt_becomes_one_line_with_caption(session):
    total_only = {"is_receipt": True, "store": "Плод и зеленчук", "total": 7.80, "items": []}
    llm = FakeLLM(total_only)
    r = (await ReceiptService(session, llm).process_photo(receipt_image(), None, note="овощи")).receipt
    assert llm.hint == "овощи"
    assert r.status == "ok", r.review_reason
    assert len(r.items) == 1 and r.items[0].total == 7.80 and r.items[0].name_original == "овощи"


async def test_find_user_by_name_and_username(session):
    from app.db.models import User
    from app.receipts.service import split_who

    session.add_all([User(name="Маша"), User(name="Иван Петров", username="ivanp", telegram_id=5)])
    await session.commit()
    svc = ReceiptService(session, FakeLLM())
    assert (await svc.find_user("маша")).name == "Маша"
    assert (await svc.find_user("Иван")).name == "Иван Петров"
    assert (await svc.find_user("@IvanP")).name == "Иван Петров"
    assert await svc.find_user("Петя") is None
    assert split_who("Маша: кино 12") == ("Маша", "кино 12")
    assert split_who("@ivanp: 12") == ("@ivanp", "12")
    assert split_who("кино 12") == (None, "кино 12")
