from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class PriceBook(TimestampMixin, Base):
    __tablename__ = "price_books"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3))


class Price(TimestampMixin, Base):
    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="amount_nonnegative"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="window_valid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    price_book_id: Mapped[UUID] = mapped_column(ForeignKey("price_books.id"))
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"), index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
