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

    _num = field_validator("qty", "unit_price", "total", mode="before")(
        lambda v: _to_float(v)
    )

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
