from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.clock import now_local
from app.db.models import Budget, Category
from app.db.session import get_session
from app.stats import budgets_status

router = APIRouter(prefix="/api", tags=["budgets"], dependencies=[Depends(current_viewer)])


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
