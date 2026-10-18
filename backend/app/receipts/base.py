"""What every part of the receipt service needs: the session, the LLM, members, categories, files."""

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import now_local
from app.config import get_settings
from app.constants import Kind
from app.db.models import Category, CategoryOverride, Item, Receipt, User
from app.family import find_user
from app.llm.client import LLMClient, get_llm
from app.receipts.money import round2
from app.receipts.parsing import income_category_key
from app.receipts.text import CategoryMatcher, normalize_name


@dataclass
class ProcessResult:
    receipt: Receipt | None = None
    duplicate_of: Receipt | None = None
    # saved, but looks like a record that is already there: the person is asked
    maybe_duplicate_of: Receipt | None = None
    not_receipt: bool = False
    error: str | None = None


def single_item(name: str, total: float | None, category_id: int | None, position: int = 0) -> Item:
    """The only line of a one-line record: a manual entry, a bank operation, a total-only receipt."""
    return Item(
        position=position,
        name_original=name,
        name_ru=name,
        name_normalized=normalize_name(name),
        qty=1,
        unit_price=round2(total),
        total=round2(total),
        category_id=category_id,
    )


class ServiceBase:
    def __init__(self, session: AsyncSession, llm: LLMClient | None = None, auto_products: bool = True):
        self.session = session
        self.llm = llm or get_llm()
        self.auto_products = auto_products
        self.settings = get_settings()

    # ---------- helpers ----------

    async def get_or_create_user(self, telegram_id: int, name: str, username: str | None = None) -> User:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            user = User(telegram_id=telegram_id, name=name, username=username)
            self.session.add(user)
            await self.session.flush()
        elif user.username != username:
            # the name is kept: it may have been changed by hand in Settings → Family
            user.username = username
        return user

    async def find_user(self, token: str) -> User | None:
        return await find_user(self.session, token)

    async def matcher(self) -> CategoryMatcher:
        cats = list(await self.session.scalars(select(Category).where(Category.kind == Kind.EXPENSE)))
        return CategoryMatcher(cats)

    async def income_category(self, name: str) -> int | None:
        return await self.session.scalar(select(Category.id).where(Category.key == income_category_key(name)))

    async def override_category(self, name: str) -> int | None:
        """The category a person once chose for this product name, if any."""
        key = normalize_name(name)
        return (await self.overrides({key})).get(key)

    async def overrides(self, names: set[str]) -> dict[str, int]:
        if not names:
            return {}
        rows = await self.session.scalars(select(CategoryOverride).where(CategoryOverride.name_normalized.in_(names)))
        return {r.name_normalized: r.category_id for r in rows}

    def _save_image(self, data: bytes, ext: str = "jpg") -> str:
        now = now_local()
        rel = Path("receipts") / f"{now:%Y}" / f"{now:%m}" / f"{uuid.uuid4().hex}.{ext}"
        path = self.settings.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel.as_posix()

    def image_abspath(self, receipt: Receipt) -> Path | None:
        if not receipt.image_path:
            return None
        return self.settings.data_dir / receipt.image_path

    async def delete_receipt(self, receipt: Receipt) -> None:
        path = self.image_abspath(receipt)
        await self.session.delete(receipt)
        await self.session.commit()
        if path and path.exists():
            path.unlink()
