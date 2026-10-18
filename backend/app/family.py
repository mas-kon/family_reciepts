"""Family members: lookup by name, bank card, e-mail address or the name the bank writes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import Kind
from app.db.models import Receipt, User
from app.receipts.text import csv_list, normalize_name


async def find_user(session: AsyncSession, token: str) -> User | None:
    """Family member by @username or by name (full or first word), case-insensitive."""
    users = list(await session.scalars(select(User)))
    t = token.strip()
    if t.startswith("@"):
        uname = t[1:].lower()
        return next((u for u in users if (u.username or "").lower() == uname), None)
    key = normalize_name(t)
    for u in users:
        full = normalize_name(u.name)
        if key == full or key == full.split(" ")[0]:
            return u
    return None


class FamilyIndex:
    """Members' cards and bank names, read once for a whole statement instead of per row."""

    def __init__(self, users: list[User]):
        self.by_card = {c[-4:]: u for u in users for c in csv_list(u.cards)}
        self.by_bank_name = {normalize_name(n): u for u in users for n in csv_list(u.bank_names)}

    @classmethod
    async def load(cls, session: AsyncSession) -> "FamilyIndex":
        return cls(list(await session.scalars(select(User))))

    def owner_by_card(self, card: str | None) -> User | None:
        return self.by_card.get(card) if card else None

    def by_bank(self, name: str | None) -> User | None:
        key = normalize_name(name or "")
        return self.by_bank_name.get(key) if key else None


async def owner_by_card(session: AsyncSession, card: str | None) -> User | None:
    if not card:
        return None
    for u in await session.scalars(select(User).where(User.cards.is_not(None))):
        if card in {c[-4:] for c in csv_list(u.cards)}:
            return u
    return None


async def owner_by_email(session: AsyncSession, address: str) -> User | None:
    for u in await session.scalars(select(User).where(User.emails.is_not(None))):
        if address in {e.lower() for e in csv_list(u.emails)}:
            return u
    return None


async def family_by_bank_name(session: AsyncSession, name: str | None) -> User | None:
    """Family member whose name in the bank (Settings → Семья) is this transfer's person."""
    key = normalize_name(name or "")
    if not key:
        return None
    for u in await session.scalars(select(User).where(User.bank_names.is_not(None))):
        if key in {normalize_name(n) for n in csv_list(u.bank_names)}:
            return u
    return None


async def apply_family_names(session: AsyncSession) -> int:
    """Marks recorded transfers to/from family members as inside the family. Called when a
    member's bank names change. Returns how many records changed. The caller commits."""
    changed = 0
    family = await FamilyIndex.load(session)
    for r in await session.scalars(
        select(Receipt).where(Receipt.counterparty.is_not(None), Receipt.kind != Kind.TRANSFER)
    ):
        peer = family.by_bank(r.counterparty)
        if peer:
            r.kind, r.peer_user_id = "transfer", peer.id
            changed += 1
    return changed
