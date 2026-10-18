from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.api.schemas import Ok
from app.db.models import Category, Recurring, User
from app.db.session import get_session
from app.scheduler import book_recurring

router = APIRouter(prefix="/api", tags=["recurring"], dependencies=[Depends(current_viewer)])


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    category_id: int | None = None
    user_id: int | None = None
    day_of_month: int = Field(1, ge=1, le=31)
    active: bool = True
    # expense | income (a salary)
    kind: str = Field("expense", pattern="^(expense|income)$")


class RecurringOut(BaseModel):
    id: int
    name: str
    amount: float
    category_id: int | None
    user_id: int | None
    day_of_month: int
    active: bool
    last_booked_month: str | None
    kind: Literal["expense", "income"]


class RecurringRun(BaseModel):
    booked: int


def rec_out(r: Recurring) -> RecurringOut:
    return RecurringOut.model_validate(r, from_attributes=True)


async def _check_recurring_refs(session: AsyncSession, data: RecurringIn) -> None:
    if data.category_id is not None and not await session.get(Category, data.category_id):
        raise HTTPException(400, "Категория: такой нет")
    if data.user_id is not None and not await session.get(User, data.user_id):
        raise HTTPException(400, "Член семьи: такого нет")


@router.get("/recurring", response_model=list[RecurringOut])
async def list_recurring(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Recurring).order_by(Recurring.day_of_month, Recurring.name))
    return [rec_out(r) for r in rows]


@router.post("/recurring", response_model=RecurringOut)
async def create_recurring(data: RecurringIn, session: AsyncSession = Depends(get_session)):
    await _check_recurring_refs(session, data)
    r = Recurring(**data.model_dump())
    session.add(r)
    await session.commit()
    return rec_out(r)


@router.put("/recurring/{rid}", response_model=RecurringOut)
async def update_recurring(rid: int, data: RecurringIn, session: AsyncSession = Depends(get_session)):
    r = await session.get(Recurring, rid)
    if not r:
        raise HTTPException(404, "Платёж не найден")
    await _check_recurring_refs(session, data)
    for k, v in data.model_dump().items():
        setattr(r, k, v)
    await session.commit()
    return rec_out(r)


@router.delete("/recurring/{rid}", response_model=Ok)
async def delete_recurring(rid: int, session: AsyncSession = Depends(get_session)):
    r = await session.get(Recurring, rid)
    if r:
        await session.delete(r)
        await session.commit()
    return Ok()


@router.post("/recurring/run", response_model=RecurringRun)
async def run_recurring(request: Request):
    booked = await book_recurring(getattr(request.app.state, "bot", None))
    return {"booked": booked}
