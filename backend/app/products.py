"""Grouping of differently named receipt lines into one product, for price tracking.

Every receipt line has name_normalized ("прясно мляко 3% 1л"). A ProductAlias maps it to a
canonical product name ("Молоко 3% 1 л"). Lines without an alias are their own product.
New names are grouped by the LLM in the background; people can merge and rename by hand.
"""

import asyncio
import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Item, ProductAlias, Receipt
from app.db.session import session_factory
from app.llm.client import LLMError
from app.stats import PRODUCT_KEY

log = logging.getLogger(__name__)

BATCH = 40
KNOWN_LIMIT = 400


_tasks: set[asyncio.Task] = set()
_lock = asyncio.Lock()


def with_alias(query):
    """Adds the alias join that PRODUCT_KEY needs."""
    return query.outerjoin(ProductAlias, ProductAlias.name_normalized == Item.name_normalized)


async def ungrouped_names(session: AsyncSession, names: list[str] | None = None) -> list[str]:
    q = (
        select(Item.name_normalized)
        .join(Receipt, Item.receipt_id == Receipt.id)
        .outerjoin(ProductAlias, ProductAlias.name_normalized == Item.name_normalized)
        .where(ProductAlias.id.is_(None), Item.total > 0, Receipt.source.in_(("photo", "email")))
        .distinct()
    )
    if names is not None:
        q = q.where(Item.name_normalized.in_(names))
    return [n for n in await session.scalars(q) if n]


async def prune_orphan_aliases(session: AsyncSession) -> int:
    """Deleting a receipt leaves its automatic aliases behind; their product names would then be
    offered to the LLM as "known products" and attached to unrelated lines. Manual ones stay."""
    res = await session.execute(
        delete(ProductAlias).where(
            ProductAlias.manual.is_(False),
            ProductAlias.name_normalized.not_in(select(Item.name_normalized).distinct()),
        )
    )
    await session.commit()
    return res.rowcount or 0


async def known_products(session: AsyncSession) -> list[str]:
    rows = await session.scalars(
        select(ProductAlias.product)
        .group_by(ProductAlias.product)
        .order_by(func.count(ProductAlias.id).desc())
        .limit(KNOWN_LIMIT)
    )
    return list(rows)


async def group_names(session: AsyncSession, llm, names: list[str] | None = None) -> int:
    """Asks the LLM to group ungrouped names (all of them, or only `names`). Returns how many
    names got a product."""
    await prune_orphan_aliases(session)
    todo = await ungrouped_names(session, names)
    done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i : i + BATCH]
        known = await known_products(session)
        try:
            res = await llm.group_products(batch, known)
        except LLMError as e:
            log.warning("product grouping failed: %s", e)
            break
        mapping = {k.strip().lower(): v.strip() for k, v in res.data.products.items() if v and v.strip()}
        for name in batch:
            product = mapping.get(name.lower())
            if product:
                session.add(ProductAlias(name_normalized=name, product=product[:300]))
                done += 1
        await session.commit()
    return done


def schedule_grouping(names: list[str], llm) -> None:
    """Runs group_names for these names in the background (one run at a time)."""
    names = [n for n in names if n]
    if not names:
        return

    async def run():
        async with _lock:
            try:
                async with session_factory()() as session:
                    await group_names(session, llm, names)
            except Exception:
                log.exception("background product grouping failed")

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def merge(session: AsyncSession, keys: list[str], product: str) -> int:
    """Puts every line of the given product keys under one product name (manual, kept forever)."""
    product = product.strip()[:300]
    names = set(await session.scalars(with_alias(select(Item.name_normalized)).where(PRODUCT_KEY.in_(keys)).distinct()))
    names |= set(await session.scalars(select(ProductAlias.name_normalized).where(ProductAlias.product.in_(keys))))
    for name in names:
        alias = await session.scalar(select(ProductAlias).where(ProductAlias.name_normalized == name))
        if alias:
            alias.product, alias.manual = product, True
        else:
            session.add(ProductAlias(name_normalized=name, product=product, manual=True))
    await session.commit()
    return len(names)


async def split(session: AsyncSession, key: str) -> int:
    """Undoes grouping: every line of this product becomes its own product again.
    Marked as manual, so automatic grouping does not merge them back."""
    aliases = list(await session.scalars(select(ProductAlias).where(ProductAlias.product == key)))
    for a in aliases:
        a.product, a.manual = a.name_normalized, True
    await session.commit()
    return len(aliases)
