import httpx
import pytest

from app import i18n
from app.locales import CATALOGS
from app.web import create_app


@pytest.fixture(autouse=True)
def _reset_language():
    i18n.use_language("ru")
    yield
    i18n.use_language("ru")


def test_catalogs_have_the_same_keys():
    keys = {lang: set(messages) for lang, messages in CATALOGS.items()}
    for lang, found in keys.items():
        assert found == keys["ru"], f"{lang}: keys differ from ru"


def test_plural_forms_match_each_language():
    forms = {"ru": ("a", "b", "c"), "en": ("a", "b"), "bg": ("a", "b")}
    for lang, expected in {
        "ru": {1: "a", 2: "b", 5: "c", 11: "c", 21: "a", 22: "b", 112: "c"},
        "en": {1: "a", 2: "b", 0: "b"},
        "bg": {1: "a", 2: "b", 0: "b"},
    }.items():
        for n, form in expected.items():
            assert forms[lang][i18n._plural_index(lang, n)] == form, (lang, n)


def test_missing_key_falls_back_to_the_key():
    assert i18n.t("no.such.key") == "no.such.key"


def test_t_uses_current_language():
    i18n.use_language("en")
    assert i18n.t("settings.language_unsupported") == "Language is not supported"
    assert i18n.t("settings.language_unsupported", lang="bg") == "Езикът не се поддържа"


async def test_language_setting_roundtrip(session):
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        got = (await c.get("/api/settings/language")).json()
        assert got["language"] == "ru" and {o["code"] for o in got["options"]} == {"ru", "en", "bg"}

        assert (await c.put("/api/settings/language", json={"language": "bg"})).status_code == 200
        assert (await c.get("/api/settings/language")).json()["language"] == "bg"
        i18n.use_language("ru")
        assert await i18n.load_language(session) == "bg"

        bad = await c.put("/api/settings/language", json={"language": "xx"})
        assert bad.status_code == 422


async def test_system_categories_follow_the_language(session):
    from sqlalchemy import select

    from app.db.models import Category
    from app.db.seed import seed_categories, translate_categories

    async def name(key):
        return await session.scalar(select(Category.name).where(Category.key == key))

    assert await name("other") == "Прочее" and await name("groceries.dairy_eggs") == "Молочные продукты и яйца"
    mine = Category(name="Моя", kind="expense")
    session.add(mine)
    renamed = await session.scalar(select(Category).where(Category.key == "pets"))
    assert renamed
    renamed.name = "Питомцы"
    await session.commit()

    await translate_categories(session, "en")
    assert await name("other") == "Other" and await name("income.salary") == "Salary"
    assert await name("pets") == "Питомцы" and mine.name == "Моя"  # hand-made names stay

    await translate_categories(session, "bg")
    assert await name("groceries") == "Хранителни стоки"
    await seed_categories(session)  # nothing is duplicated
    assert await session.scalar(select(Category).where(Category.key == "other"))


async def test_old_categories_without_keys_are_adopted(session):
    from sqlalchemy import select, update

    from app.db.models import Category
    from app.db.seed import seed_categories

    await session.execute(update(Category).values(key=None))
    await session.commit()
    await seed_categories(session)
    parent = await session.scalar(select(Category).where(Category.key == "groceries"))
    child = await session.scalar(select(Category).where(Category.key == "groceries.frozen"))
    assert parent and child and child.parent_id == parent.id
    assert await session.scalar(select(Category.id).where(Category.key == "income.other"))


def test_placeholders_match_in_every_language():
    import string

    def fields(text):
        return {f for _, f, _, _ in string.Formatter().parse(text) if f}

    for key, ru in CATALOGS["ru"].items():
        want = fields(ru) if isinstance(ru, str) else None
        for lang in ("en", "bg"):
            got = CATALOGS[lang][key]
            if want is not None:
                assert fields(got) == want, f"{lang}/{key}: placeholders differ from ru"


def test_texts_follow_the_language(session):
    from app.constants import income_default, placeholder_names
    from app.reports import month_title

    assert month_title("2026-03") == "Март 2026"
    i18n.use_language("en")
    assert month_title("2026-03") == "March 2026"
    assert income_default() == "Income"
    assert "Поступление" in placeholder_names("record.income_default")  # records made earlier still match
    assert "Постъпление" in placeholder_names("record.income_default")
    i18n.use_language("bg")
    assert month_title("2026-03") == "Март 2026" and i18n.t("bot.cb_kept") == "Оставих го"


async def test_bot_reply_in_english(session):
    from app.bot.ui import format_receipt
    from app.receipts.service import ReceiptService
    from tests.conftest import LIDL, FakeLLM, receipt_image

    res = await ReceiptService(session, FakeLLM(LIDL)).process_photo(receipt_image(), None)
    i18n.use_language("en")
    text = await format_receipt(session, res.receipt)
    assert "lines:" in text and "позиций" not in text


def test_prompts_name_the_family_language():
    from app.llm.prompt import localize, receipt_system

    assert "in Russian" in receipt_system(["x"]) and "{lang}" not in receipt_system(["x"])
    i18n.use_language("en")
    p = receipt_system(["x"])
    assert "in English" in p and "in Russian" not in p and "{deposit}" not in p and "Bottle deposit" in p
    i18n.use_language("bg")
    assert "in Bulgarian" in localize("a name in {lang}")


def test_instructions_are_english():
    import re

    from app.ask import TOOLS
    from app.llm import prompt

    texts = [getattr(prompt, n) for n in dir(prompt) if n.endswith(("_SYSTEM", "_USER"))] + [str(TOOLS)]
    for text in texts:
        # Bulgarian receipt words are kept on purpose; Russian instructions are not
        assert not re.search(r"\b(?:Верни|Ты|Правила|Категории)\b", text)
