from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.config import get_settings
from app.db.session import get_session
from app.llm.usage import balances, usage_report

router = APIRouter(prefix="/api", tags=["llm"], dependencies=[Depends(current_viewer)])


@router.get("/llm/balance")
async def llm_balance(fresh: bool = False):
    s = get_settings()
    return {"alert_below": s.llm_balance_alert, "providers": await balances(fresh)}


@router.get("/llm/usage")
async def llm_usage(days: int = Query(30, ge=1, le=366), session: AsyncSession = Depends(get_session)):
    return await usage_report(session, days)


@router.get("/meta")
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
