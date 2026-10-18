from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _to_float(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        v = v.replace(" ", "").replace(",", ".")
        v = "".join(ch for ch in v if ch.isdigit() or ch in ".-")
        if not v or v in {".", "-"}:
            return None
    return float(v)


class ParsedItem(BaseModel):
    name_original: str
    name_ru: str | None = None
    qty: float | None = 1.0
    unit_price: float | None = None
    total: float
    category: str | None = None
    # warranty in months for electronics and appliances, null for everything else
    warranty_months: int | None = None

    _num = field_validator("qty", "unit_price", "total", mode="before")(
        lambda v: _to_float(v)
    )

    @field_validator("warranty_months", mode="before")
    @classmethod
    def _months(cls, v):
        f = _to_float(v)
        return int(f) if f and 0 < f <= 240 else None

    @field_validator("qty", mode="after")
    @classmethod
    def _qty(cls, v):
        return v if v else 1.0


class ParsedReceipt(BaseModel):
    is_receipt: bool = True
    store: str | None = None
    purchased_at: datetime | None = None
    total: float | None = None
    items: list[ParsedItem] = Field(default_factory=list)

    _num = field_validator("total", mode="before")(lambda v: _to_float(v))

    @field_validator("purchased_at", mode="before")
    @classmethod
    def _dt(cls, v):
        if not v:
            return None
        if isinstance(v, str):
            v = v.strip().replace(" ", "T", 1)
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d.%m.%Y"):
                try:
                    return datetime.strptime(v[: len(datetime.now().strftime(fmt))], fmt)
                except ValueError:
                    continue
            return None
        return v


class ParsedManual(BaseModel):
    name: str
    amount: float
    category: str | None = None

    _num = field_validator("amount", mode="before")(lambda v: _to_float(v))


def _to_dt(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    v = str(v).strip().replace(" ", "T", 1)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(v[: len(datetime(2000, 1, 1).strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


class ParsedBankTx(BaseModel):
    amount: float
    merchant: str | None = None
    date: datetime | None = None
    # last 4 digits of the card, if the message shows them
    card: str | None = None
    is_expense: bool = True

    _num = field_validator("amount", mode="before")(lambda v: abs(_to_float(v) or 0))
    _dt = field_validator("date", mode="before")(lambda v: _to_dt(v))

    @field_validator("card", mode="before")
    @classmethod
    def _card(cls, v):
        digits = "".join(ch for ch in str(v or "") if ch.isdigit())
        return digits[-4:] if len(digits) >= 4 else None


class ParsedBank(BaseModel):
    transactions: list[ParsedBankTx] = Field(default_factory=list)


class ParsedVoice(BaseModel):
    has_speech: bool = True
    is_expense: bool = True
    transcript: str = ""
    # family member the purchase is for, if said ("Маше на кино 12")
    who: str | None = None
    name: str | None = None
    amount: float | None = None

    _num = field_validator("amount", mode="before")(lambda v: _to_float(v))


class ParsedProducts(BaseModel):
    # name_normalized -> canonical product name
    products: dict[str, str] = Field(default_factory=dict)
