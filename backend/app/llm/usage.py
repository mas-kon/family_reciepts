"""What the LLM costs: a log of every request and balances at the providers.

Costs are in USD, as providers bill them. OpenRouter reports for each request:
- cost: charged to the OpenRouter balance (for a BYOK request only OpenRouter's fee, often 0);
- upstream_inference_cost: what the provider charges, paid from your own key when is_byok.
"""

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import LLMCall

log = logging.getLogger(__name__)

TASK_LABEL = {
    "receipt": "Чеки по фото",
    "receipt_text": "Электронные чеки",
    "manual": "Траты текстом",
    "bank": "Банк и выписки",
    "voice": "Голосовые",
    "products": "Склейка товаров",
    "comment": "Комментарий к отчёту",
    "ask": "Вопросы",
    "other": "Прочее",
}


def _usage_fields(resp) -> dict:
    usage = resp.usage.model_dump() if getattr(resp, "usage", None) else {}
    details = usage.get("cost_details") or {}
    return {
        "provider": getattr(resp, "provider", None),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost": usage.get("cost"),
        "upstream_cost": details.get("upstream_inference_cost"),
        "is_byok": bool(usage.get("is_byok")),
    }


async def record_call(task: str, model: str, resp, error: Exception | None = None) -> None:
    """Saves one request. Never raises: the log must not break recognition."""
    from app.db.session import session_factory
    from app.receipts.service import now_local

    try:
        row = LLMCall(created_at=now_local(), task=task, model=model, ok=error is None)
        if error is not None:
            row.error = f"{type(error).__name__}: {error}"[:300]
        else:
            for k, v in _usage_fields(resp).items():
                setattr(row, k, v)
        async with session_factory()() as session:
            session.add(row)
            await session.commit()
    except Exception as e:
        log.warning("could not record LLM usage: %s", e)


# ---------- usage report ----------


async def usage_report(session: AsyncSession, days: int = 30) -> dict:
    from app.receipts.service import now_local

    since = (now_local() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    cols = (
        func.count(LLMCall.id).label("calls"),
        func.sum(case((LLMCall.ok.is_(False), 1), else_=0)).label("failed"),
        func.coalesce(func.sum(LLMCall.cost), 0).label("cost"),
        func.coalesce(func.sum(case((LLMCall.is_byok.is_(True), LLMCall.upstream_cost), else_=0)), 0).label("byok_cost"),
        func.sum(case((LLMCall.is_byok.is_(True), 1), else_=0)).label("byok_calls"),
    )

    async def group(*keys):
        q = select(*keys, *cols).where(LLMCall.created_at >= since).group_by(*keys).order_by(func.count(LLMCall.id).desc())
        return [dict(r._mapping) for r in await session.execute(q)]

    day = func.strftime("%Y-%m-%d", LLMCall.created_at)
    total = (await session.execute(select(*cols).where(LLMCall.created_at >= since))).one()._mapping
    by_task = await group(LLMCall.task)
    for r in by_task:
        r["label"] = TASK_LABEL.get(r["task"], r["task"])
    return {
        "days": days,
        "total": dict(total),
        "by_task": by_task,
        "by_model": await group(LLMCall.model, LLMCall.provider),
        "by_day": sorted(await group(day.label("day")), key=lambda r: r["day"]),
    }


# ---------- balances ----------

_cache: dict[str, tuple[float, list]] = {}
CACHE_SECONDS = 120


def _get_json(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _openrouter(base_url: str, key: str) -> dict:
    base = base_url.rstrip("/")
    out: dict = {"provider": "OpenRouter", "currency": "USD", "url": "https://openrouter.ai/settings/credits"}
    try:
        c = _get_json(f"{base}/credits", key)["data"]
        out["balance"] = round(c["total_credits"] - c["total_usage"], 4)
        out["total_credits"] = c["total_credits"]
    except Exception as e:  # a key without access to credits still has its own limit below
        out["error"] = f"Баланс счёта недоступен: {e}"
    try:
        k = _get_json(f"{base}/key", key)["data"]
        out["key"] = {
            "limit": k.get("limit"),
            "limit_remaining": k.get("limit_remaining"),
            "limit_reset": k.get("limit_reset"),
            "usage_daily": k.get("usage_daily"),
            "usage_monthly": k.get("usage_monthly"),
            "byok_usage_monthly": k.get("byok_usage_monthly"),
            "is_free_tier": k.get("is_free_tier"),
            "free_requests_remaining": (k.get("free_model_daily_requests") or {}).get("remaining"),
        }
    except Exception as e:
        out.setdefault("error", f"Данные ключа недоступны: {e}")
    return out


def _deepseek(key: str) -> dict:
    out: dict = {"provider": "DeepSeek", "url": "https://platform.deepseek.com/usage"}
    try:
        d = _get_json("https://api.deepseek.com/user/balance", key)
        info = next(iter(d.get("balance_infos") or []), {})
        out["currency"] = info.get("currency", "USD")
        out["balance"] = float(info.get("total_balance") or 0)
    except Exception as e:
        out["error"] = f"Баланс недоступен: {e}"
    return out


def _fetch_balances() -> list[dict]:
    s = get_settings()
    out = []
    if "openrouter.ai" in s.llm_base_url and s.llm_api_key:
        out.append(_openrouter(s.llm_base_url, s.llm_api_key))
    if s.deepseek_api_key:
        out.append(_deepseek(s.deepseek_api_key))
    return out


async def balances(fresh: bool = False) -> list[dict]:
    """Balances at the providers that tell them. Cached for a couple of minutes."""
    hit = _cache.get("all")
    if hit and not fresh and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    data = await asyncio.to_thread(_fetch_balances)
    _cache["all"] = (time.monotonic(), data)
    return data


def low_balances(items: list[dict], threshold: float) -> dict[str, str]:
    """Balances below the threshold: {key: human-readable warning}."""
    out = {}
    for b in items:
        cur = "$" if b.get("currency", "USD") == "USD" else f" {b.get('currency')}"
        if b.get("balance") is not None and b["balance"] < threshold:
            out[f"{b['provider']}:balance"] = f"{b['provider']}: на счёте осталось {b['balance']:.2f}{cur}"
        key = b.get("key") or {}
        if key.get("limit") and key.get("limit_remaining") is not None and key["limit_remaining"] < threshold:
            out[f"{b['provider']}:key"] = f"{b['provider']}: до лимита ключа осталось {key['limit_remaining']:.2f}{cur}"
    return out


# warnings already sent; a balance that recovers is forgotten, so it warns again next time
_alerted: set[str] = set()


async def check_balance(bot) -> list[str]:
    """Daily job: warns the group once when a balance gets low."""
    s = get_settings()
    if not s.llm_balance_alert or not bot or not s.notify_chat_id:
        return []
    try:
        low = low_balances(await balances(fresh=True), s.llm_balance_alert)
    except Exception as e:
        log.warning("balance check failed: %s", e)
        return []
    new = [msg for k, msg in low.items() if k not in _alerted]
    _alerted.intersection_update(low)
    _alerted.update(low)
    if new:
        await bot.send_message(
            s.notify_chat_id,
            "💳 Пора пополнить баланс нейросети:\n" + "\n".join(f"• {m}" for m in new)
            + "\nПодробности в вебе: Настройки → Нейросеть.",
        )
    return new
