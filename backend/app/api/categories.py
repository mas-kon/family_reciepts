from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_viewer
from app.db.models import Category, Item
from app.db.session import get_session

router = APIRouter(prefix="/api", tags=["categories"], dependencies=[Depends(current_viewer)])


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
    same = await session.scalar(
        select(Category.id).where(
            func.lower(Category.name) == data.name.strip().lower(),
            Category.parent_id.is_(None) if data.parent_id is None else Category.parent_id == data.parent_id,
        )
    )
    if same:
        raise HTTPException(409, "Такая категория уже есть")
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
