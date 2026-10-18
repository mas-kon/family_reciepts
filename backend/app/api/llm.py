from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.config import get_settings
from app.db.session import get_session
from app.llm.usage import balances, usage_report

router = APIRouter(prefix="/api", tags=["llm"], dependencies=[Depends(current_viewer)])


class KeyLimits(BaseModel):
    limit: float | None
    limit_remaining: float | None
    limit_reset: str | None
    usage_daily: float | None
    usage_monthly: float | None
    byok_usage_monthly: float | None
    is_free_tier: bool | None
    free_requests_remaining: int | None


class ProviderBalance(BaseModel):
    provider: str
    currency: str | None = None
    url: str
    balance: float | None = None
    total_credits: float | None = None
    error: str | None = None
    key: KeyLimits | None = None


class BalanceOut(BaseModel):
    alert_below: float
    providers: list[ProviderBalance]


Count = Annotated[int, BeforeValidator(lambda v: v or 0)]  # SUM over no rows is NULL


class UsageRow(BaseModel):
    calls: Count
    failed: Count
    # USD charged to the OpenRouter balance
    cost: float
    # USD charged to own provider keys (BYOK)
    byok_cost: float
    byok_calls: Count


class TaskUsage(UsageRow):
    task: str
    label: str


class ModelUsage(UsageRow):
    model: str
    provider: str | None


class DayUsage(UsageRow):
    day: str


class UsageOut(BaseModel):
    days: int
    total: UsageRow
    by_task: list[TaskUsage]
    by_model: list[ModelUsage]
    by_day: list[DayUsage]


class MetaOut(BaseModel):
    models: list[str]
    llm_base_url: str
    text_models: list[str]
    strong_models: list[str]
    audio_models: list[str]
    ask_models: list[str]
    email_enabled: bool
    email_address: str | None
    warranty_remind_days: int


@router.get("/llm/balance", response_model=BalanceOut)
async def llm_balance(fresh: bool = False):
    s = get_settings()
    return {"alert_below": s.llm_balance_alert, "providers": await balances(fresh)}


@router.get("/llm/usage", response_model=UsageOut)
async def llm_usage(days: int = Query(30, ge=1, le=366), session: AsyncSession = Depends(get_session)):
    return await usage_report(session, days)


@router.get("/meta", response_model=MetaOut)
async def meta():
    s = get_settings()
    return {
        "models": s.models,
        "llm_base_url": s.llm_base_url,
        "text_models": s.text_models,
        "strong_models": s.strong_models,
        "audio_models": s.audio_models,
        "ask_models": s.ask_models,
        "email_enabled": bool(s.imap_host),
        "email_address": s.imap_user if s.imap_host else None,
        "warranty_remind_days": s.warranty_remind_days,
    }
