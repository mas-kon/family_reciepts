from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.api.schemas import Ok
from app.db.models import Receipt, User
from app.db.session import get_session
from app.family import apply_family_names
from app.i18n import t

router = APIRouter(prefix="/api", tags=["users"], dependencies=[Depends(current_viewer)])


class UserOut(BaseModel):
    id: int
    name: str
    username: str | None
    has_telegram: bool
    cards: str
    emails: str
    # how the bank writes this person in transfers, comma-separated
    bank_names: str


class UserSaved(UserOut):
    marked_transfers: int


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        name=u.name,
        username=u.username,
        has_telegram=u.telegram_id is not None,
        cards=u.cards or "",
        emails=u.emails or "",
        bank_names=u.bank_names or "",
    )


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


@router.get("/users", response_model=list[UserOut])
async def users(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(User).order_by(User.name))
    return [user_out(u) for u in rows]


@router.post("/users", response_model=UserOut)
async def create_user(data: UserIn, session: AsyncSession = Depends(get_session)):
    """Family member without Telegram, e.g. a child: expenses can be booked for them."""
    u = User(name=data.name.strip())
    session.add(u)
    await session.commit()
    return user_out(u)


@router.patch("/users/{uid}", response_model=UserSaved)
async def update_user(uid: int, data: UserPatch, session: AsyncSession = Depends(get_session)):
    u = await session.get(User, uid)
    if not u:
        raise HTTPException(404, t("api.member_not_found"))
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
        # transfers to this person recorded before become inside-the-family too
        marked = await apply_family_names(session)
    await session.commit()
    return UserSaved(**user_out(u).model_dump(), marked_transfers=marked)


@router.delete("/users/{uid}", response_model=Ok)
async def delete_user(uid: int, session: AsyncSession = Depends(get_session)):
    u = await session.get(User, uid)
    if not u:
        return Ok()
    used = await session.scalar(select(func.count(Receipt.id)).where(Receipt.user_id == uid))
    if used:
        raise HTTPException(409, t("api.member_has_expenses", count=used))
    await session.delete(u)
    await session.commit()
    return Ok()
