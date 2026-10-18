from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.bank import apply_family_names
from app.config import get_settings
from app.db.models import Budget, Category, Item, Receipt, Recurring, User
from app.db.session import get_session
from app.receipts.service import now_local
from app.scheduler import book_recurring
from app.stats import budgets_status

router = APIRouter(prefix="/api", tags=["settings"], dependencies=[Depends(current_viewer)])


# ---------- LLM balance and usage ----------


@router.get("/llm/balance")
async def llm_balance(fresh: bool = False):
    from app.llm.usage import balances

    s = get_settings()
    return {"alert_below": s.llm_balance_alert, "providers": await balances(fresh)}


@router.get("/llm/usage")
async def llm_usage(days: int = Query(30, ge=1, le=366), session: AsyncSession = Depends(get_session)):
    from app.llm.usage import usage_report

    return await usage_report(session, days)


# ---------- meta / users ----------


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


def user_out(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "username": u.username,
        "has_telegram": u.telegram_id is not None,
        "cards": u.cards or "",
        "emails": u.emails or "",
        "bank_names": u.bank_names or "",
    }


def _clean_list(value: str | None, digits: bool) -> str | None:
    """'1234, *5678' -> '1234,5678'; e-mails are lower-cased."""
    parts = []
    for p in (value or "").replace(";", ",").split(","):
        p = p.strip()
        if digits:
            p = "".join(ch for ch in p if ch.isdigit())[-4:]
            if len(p) < 4:
                continue
        else:
            p = p.lower()
            if "@" not in p:
                continue
        parts.append(p)
    return ",".join(dict.fromkeys(parts)) or None


def _clean_names(value: str | None) -> str | None:
    parts = [" ".join(p.split()) for p in (value or "").replace(";", ",").split(",")]
    return ",".join(dict.fromkeys(p for p in parts if p)) or None


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    # last 4 digits of bank cards, comma-separated
    cards: str | None = None
    emails: str | None = None
    # how the bank writes this person in transfers, comma-separated
    bank_names: str | None = None


@router.get("/users")
async def users(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(User).order_by(User.name))
    return [user_out(u) for u in rows]


@router.post("/users")
async def create_user(data: UserIn, session: AsyncSession = Depends(get_session)):
    """Family member without Telegram, e.g. a child: expenses can be booked for them."""
    u = User(name=data.name.strip())
    session.add(u)
    await session.commit()
    return user_out(u)


@router.patch("/users/{uid}")
async def update_user(uid: int, data: UserPatch, session: AsyncSession = Depends(get_session)):
    u = await session.get(User, uid)
    if not u:
        raise HTTPException(404, "Член семьи не найден")
    fields = data.model_dump(exclude_unset=True)
    if fields.get("name"):
        u.name = fields["name"].strip()
    if "cards" in fields:
        u.cards = _clean_list(fields["cards"], digits=True)
    if "emails" in fields:
        u.emails = _clean_list(fields["emails"], digits=False)
    marked = 0
    if "bank_names" in fields:
        u.bank_names = _clean_names(fields["bank_names"])
        await session.commit()
        # transfers to this person recorded before become inside-the-family too
        marked = await apply_family_names(session)
    await session.commit()
    return {**user_out(u), "marked_transfers": marked}


@router.delete("/users/{uid}")
async def delete_user(uid: int, session: AsyncSession = Depends(get_session)):
    u = await session.get(User, uid)
    if not u:
        return {"ok": True}
    used = await session.scalar(select(func.count(Receipt.id)).where(Receipt.user_id == uid))
    if used:
        raise HTTPException(409, f"На этого человека записано трат: {used}. Сначала перенесите их.")
    await session.delete(u)
    await session.commit()
    return {"ok": True}


# ---------- categories ----------


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    kind: str = Field("expense", pattern="^(expense|income)$")


class CategoryPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    sort_order: int | None = None


@router.get("/categories")
async def categories(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Category).order_by(Category.sort_order, Category.id))
    return [cat_out(c) for c in rows]


def cat_out(c: Category) -> dict:
    return {"id": c.id, "name": c.name, "parent_id": c.parent_id, "sort_order": c.sort_order, "kind": c.kind}


@router.post("/categories")
async def create_category(data: CategoryIn, session: AsyncSession = Depends(get_session)):
    if data.parent_id:
        parent = await session.get(Category, data.parent_id)
        if not parent or parent.parent_id:
            raise HTTPException(400, "Родителем может быть только категория верхнего уровня")
        data.kind = parent.kind
    order = await session.scalar(
        select(func.coalesce(func.max(Category.sort_order), 0)).where(
            Category.parent_id.is_(None) if data.parent_id is None else Category.parent_id == data.parent_id
        )
    )
    c = Category(name=data.name.strip(), parent_id=data.parent_id, sort_order=(order or 0) + 1, kind=data.kind)
    session.add(c)
    await session.commit()
    return cat_out(c)


@router.patch("/categories/{cid}")
async def patch_category(cid: int, data: CategoryPatch, session: AsyncSession = Depends(get_session)):
    c = await session.get(Category, cid)
    if not c:
        raise HTTPException(404, "Категория не найдена")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v.strip() if isinstance(v, str) else v)
    await session.commit()
    return cat_out(c)


@router.delete("/categories/{cid}")
async def delete_category(cid: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(Category, cid)
    if not c:
        raise HTTPException(404, "Категория не найдена")
    used = await session.scalar(select(func.count(Item.id)).where(Item.category_id == cid))
    children = await session.scalar(select(func.count(Category.id)).where(Category.parent_id == cid))
    if used or children:
        raise HTTPException(409, "Категория используется: сначала перенесите позиции и подкатегории")
    await session.delete(c)
    await session.commit()
    return {"ok": True}


# ---------- budgets ----------


class BudgetIn(BaseModel):
    category_id: int
    amount: float = Field(gt=0)


@router.get("/budgets")
async def budgets(month: str | None = None, session: AsyncSession = Depends(get_session)):
    month = month or f"{now_local():%Y-%m}"
    return {"month": month, "items": await budgets_status(session, month)}


@router.put("/budgets")
async def put_budget(data: BudgetIn, session: AsyncSession = Depends(get_session)):
    if not await session.get(Category, data.category_id):
        raise HTTPException(404, "Категория не найдена")
    b = await session.scalar(select(Budget).where(Budget.category_id == data.category_id))
    if b:
        b.amount = data.amount
    else:
        session.add(Budget(category_id=data.category_id, amount=data.amount))
    await session.commit()
    return {"ok": True}


@router.delete("/budgets/{bid}")
async def delete_budget(bid: int, session: AsyncSession = Depends(get_session)):
    b = await session.get(Budget, bid)
    if b:
        await session.delete(b)
        await session.commit()
    return {"ok": True}


# ---------- recurring ----------


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    category_id: int | None = None
    user_id: int | None = None
    day_of_month: int = Field(1, ge=1, le=31)
    active: bool = True
    # expense | income (a salary)
    kind: str = Field("expense", pattern="^(expense|income)$")


def rec_out(r: Recurring) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "amount": r.amount,
        "category_id": r.category_id,
        "user_id": r.user_id,
        "day_of_month": r.day_of_month,
        "active": r.active,
        "last_booked_month": r.last_booked_month,
        "kind": r.kind,
    }


@router.get("/recurring")
async def list_recurring(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Recurring).order_by(Recurring.day_of_month, Recurring.name))
    return [rec_out(r) for r in rows]


@router.post("/recurring")
async def create_recurring(data: RecurringIn, session: AsyncSession = Depends(get_session)):
    r = Recurring(**data.model_dump())
    session.add(r)
    await session.commit()
    return rec_out(r)


@router.put("/recurring/{rid}")
async def update_recurring(rid: int, data: RecurringIn, session: AsyncSession = Depends(get_session)):
    r = await session.get(Recurring, rid)
    if not r:
        raise HTTPException(404, "Платёж не найден")
    for k, v in data.model_dump().items():
        setattr(r, k, v)
    await session.commit()
    return rec_out(r)


@router.delete("/recurring/{rid}")
async def delete_recurring(rid: int, session: AsyncSession = Depends(get_session)):
    r = await session.get(Recurring, rid)
    if r:
        await session.delete(r)
        await session.commit()
    return {"ok": True}


@router.post("/recurring/run")
async def run_recurring(request: Request):
    booked = await book_recurring(getattr(request.app.state, "bot", None))
    return {"booked": booked}
