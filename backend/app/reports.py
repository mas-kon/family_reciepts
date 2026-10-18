"""Monthly report: a PNG chart plus a short text summary."""

import asyncio
import html
import io
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_local
from app.config import get_settings
from app.llm.client import LLMError, get_llm
from app.llm.prompt import COMMENT_SYSTEM
from app.stats import budgets_status, month_bounds, prev_month, summary

log = logging.getLogger(__name__)

SUMMARY_KEYS = ("total", "receipts", "by_category", "by_subcategory", "by_user", "by_store", "top_items", "income")

MONTHS_RU = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]


def month_title(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{MONTHS_RU[m - 1].capitalize()} {y}"


def render_chart(month: str, by_category: list[dict]) -> bytes:
    # matplotlib is heavy: imported on first use. Figure (not pyplot) keeps no global state.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    rows = [r for r in by_category if r["amount"] > 0][:10][::-1]
    fig = Figure(figsize=(8, max(3, 0.45 * len(rows) + 1.2)), dpi=120)
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    names = [r["name"] or "Без категории" for r in rows]
    values = [r["amount"] for r in rows]
    bars = ax.barh(names, values, color="#3b82f6")
    ax.bar_label(bars, labels=[f"{v:.2f} €" for v in values], padding=4, fontsize=9)
    ax.set_title(f"Расходы: {month_title(month)}", fontsize=13, loc="left")
    ax.spines[["top", "right", "bottom"]].set_visible(False)
    ax.xaxis.set_visible(False)
    ax.margins(x=0.18)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    return buf.getvalue()


async def month_comment(session: AsyncSession, month: str, cur: dict, prev: dict, llm=None) -> str | None:
    """2–4 sentences from the LLM about what changed this month. None if the LLM is unavailable."""
    if not cur["total"]:
        return None

    def pick(s: dict) -> dict:
        return {k: s[k] for k in SUMMARY_KEYS}

    data = {
        "month": month_title(month),
        "this_month": pick(cur),
        "previous_month": pick(prev),
        "budgets": await budgets_status(session, month),
    }
    llm = llm or get_llm()
    try:
        text, _ = await llm.complete_text(
            [
                {"role": "system", "content": COMMENT_SYSTEM},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False, default=str)},
            ],
            get_settings().text_models,
        )
    except LLMError as e:
        log.warning("month comment failed: %s", e)
        return None
    return html.escape(text.strip()[:900])


async def build_monthly_report(
    session: AsyncSession, month: str, with_comment: bool = True, llm=None
) -> tuple[str, bytes | None]:
    start, end = month_bounds(month)
    cur = await summary(session, start, end)
    before = prev_month(start.date())
    pstart, pend = month_bounds(before)
    prev = await summary(session, pstart, pend)

    lines = [f"📊 <b>{month_title(month)}</b>", f"Расходы: <b>{cur['total']:.2f} €</b>"]
    if prev["total"]:
        diff = (cur["total"] - prev["total"]) / prev["total"] * 100
        sign = "+" if diff >= 0 else ""
        lines.append(f"К прошлому месяцу: {sign}{diff:.0f}%")
    if income := cur["income"]["total"]:
        lines.append(f"Доходы: <b>{income:.2f} €</b>, остаток: {income - cur['total']:+.2f} €")
    if with_comment and (comment := await month_comment(session, month, cur, prev, llm)):
        lines += ["", f"💬 {comment}"]
    if cur["by_user"]:
        lines.append("")
        lines += [f"👤 {u['name'] or '—'}: {u['amount']:.2f} €" for u in cur["by_user"]]
    if cur["by_category"]:
        lines.append("")
        lines += [f"• {c['name'] or 'Без категории'}: {c['amount']:.2f} €" for c in cur["by_category"][:8]]
    if cur["by_store"]:
        lines.append("")
        lines.append("Магазины: " + ", ".join(s["store"] for s in cur["by_store"][:5]))

    chart = await asyncio.to_thread(render_chart, month, cur["by_category"]) if cur["by_category"] else None
    return "\n".join(lines), chart


def last_month() -> str:
    return prev_month(now_local().date())
