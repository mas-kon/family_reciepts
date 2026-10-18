from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(100))
    # last 4 digits of this person's bank cards, comma-separated: bank messages are booked for them
    cards: Mapped[str | None] = mapped_column(String(200))
    # e-mail addresses, comma-separated: receipts sent from them are booked for this person
    emails: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("parent_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], lazy="joined")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # photo | manual | recurring | bank | voice | email
    source: Mapped[str] = mapped_column(String(20), default="photo")
    store: Mapped[str | None] = mapped_column(String(200))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    total: Mapped[float | None] = mapped_column(Float)  # EUR
    image_path: Mapped[str | None] = mapped_column(String(300))
    qr_raw: Mapped[str | None] = mapped_column(String(300))
    fiscal_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    # id from outside (e-mail Message-ID, bank transaction hash) to avoid booking twice
    external_id: Mapped[str | None] = mapped_column(String(300), unique=True)
    # records booked from one bank statement share it, so the whole import can be deleted at once
    import_id: Mapped[str | None] = mapped_column(String(40), index=True)
    # pending | ok | needs_review | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    review_reason: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(200))
    raw_llm_json: Mapped[dict | None] = mapped_column(JSON)
    # text of an electronic receipt (e-mail, PDF), kept so it can be re-read by another model
    source_text: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(Integer)
    # bot's reply about this receipt: replying to it in the chat edits the receipt
    bot_message_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User | None] = relationship(lazy="joined")
    items: Mapped[list["Item"]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="Item.position",
        lazy="selectin",
    )


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name_original: Mapped[str] = mapped_column(String(300))
    name_ru: Mapped[str | None] = mapped_column(String(300))
    name_normalized: Mapped[str] = mapped_column(String(300), index=True)
    qty: Mapped[float] = mapped_column(Float, default=1.0)
    unit_price: Mapped[float | None] = mapped_column(Float)
    total: Mapped[float] = mapped_column(Float)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    warranty_until: Mapped[date | None] = mapped_column(Date, index=True)
    warranty_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    receipt: Mapped[Receipt] = relationship(back_populates="items")
    category: Mapped[Category | None] = relationship(lazy="joined")


class CategoryOverride(Base):
    """Remembered manual category choice for a product name."""

    __tablename__ = "category_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_normalized: Mapped[str] = mapped_column(String(300), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProductAlias(Base):
    """Groups differently named lines of the same product ("ПРЯСНО МЛЯКО 3% 1Л", "Мляко 3% 1л")
    under one canonical name, for price tracking."""

    __tablename__ = "product_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_normalized: Mapped[str] = mapped_column(String(300), unique=True)
    product: Mapped[str] = mapped_column(String(300), index=True)
    # manual merges are never overwritten by the automatic grouping
    manual: Mapped[bool] = mapped_column(Boolean, default=False)


class Budget(Base):
    """Monthly spending limit for a category (and its children), in EUR."""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), unique=True
    )
    amount: Mapped[float] = mapped_column(Float)

    category: Mapped[Category] = relationship(lazy="joined")


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("budget_id", "month", "level"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    level: Mapped[int] = mapped_column(Integer)  # 80 | 100
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recurring(Base):
    """Regular payment that is booked automatically each month."""

    __tablename__ = "recurring"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float)  # EUR
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    day_of_month: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_booked_month: Mapped[str | None] = mapped_column(String(7))

    category: Mapped[Category | None] = relationship(lazy="joined")
    user: Mapped[User | None] = relationship(lazy="joined")
