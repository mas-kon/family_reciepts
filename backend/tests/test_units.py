import pytest

from app.llm.client import extract_json
from app.llm.schema import ParsedReceipt
from app.receipts.qr import parse_fiscal_qr
from app.receipts.service import parse_manual_text
from app.receipts.text import normalize_name


def test_parse_fiscal_qr():
    qr = parse_fiscal_qr("DT123456*0012345*2026-01-15*14:30:25*23.40")
    assert qr.device == "DT123456"
    assert qr.number == "12345"
    assert qr.amount == 23.40
    assert qr.purchased_at.hour == 14
    assert qr.fiscal_key == "DT123456:12345:20260115"


@pytest.mark.parametrize("text", ["hello", "https://lidl.bg", "DT1*1*2026-13-45*10:00:00*1.00"])
def test_parse_fiscal_qr_rejects_garbage(text):
    assert parse_fiscal_qr(text) is None


def test_extract_json_from_fenced_answer():
    answer = 'Вот результат:\n```json\n{"is_receipt": true, "items": []}\n```\nГотово'
    assert extract_json(answer) == {"is_receipt": True, "items": []}


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError):
        extract_json("не могу прочитать")


def test_parsed_receipt_tolerates_messy_numbers():
    r = ParsedReceipt.model_validate(
        {"total": "23,40 €", "purchased_at": "2026-01-15 14:30", "items": [{"name_original": "X", "total": "1,5", "qty": None}]}
    )
    assert r.total == 23.40
    assert r.items[0].total == 1.5
    assert r.items[0].qty == 1.0
    assert r.purchased_at.minute == 30


def test_normalize_name():
    assert normalize_name("  Прясно  мляко, 3% 1Л ") == "прясно мляко 3% 1л"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("такси 12", ("Такси", 12.0)),
        ("кофе 3,50", ("Кофе", 3.5)),
        ("подарок маме 25€", ("Подарок маме", 25.0)),
        ("кофе 3,50 лв", None),
        ("просто текст", None),
    ],
)
def test_parse_manual_text(text, expected):
    assert parse_manual_text(text) == expected


def test_web_base_url_gets_scheme():
    from app.config import Settings

    assert Settings(web_base_url="chek.example.com/").web_base_url == "https://chek.example.com"
    assert Settings(web_base_url="http://10.0.0.5:8000").web_base_url == "http://10.0.0.5:8000"
    assert Settings(web_base_url="").web_base_url == ""


def test_statement_is_not_a_receipt():
    from app.bank import looks_like_statement

    icard = "Месечно извлечение септември 2026\nIBAN: BG09INTF40012082542347\nНачален баланс 2.43 EUR\nКраен баланс 1.26 EUR"
    revolut = "Выписка для EUR\nIBAN LT903250089798526389\nСведения о балансе\nНачальный баланс"
    receipt = "LIDL БЪЛГАРИЯ\nМЛЯКО 1.29\nОБЩА СУМА 12.40 EUR\nКАРТА 12.40"
    assert looks_like_statement(icard) and looks_like_statement(revolut)
    assert not looks_like_statement(receipt) and not looks_like_statement("")
