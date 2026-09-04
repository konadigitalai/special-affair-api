from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid7

if TYPE_CHECKING:
    from app.modules.catalog.models import Variant


class Cart(TimestampMixin, Base):
    __tablename__ = "carts"
    __table_args__ = (CheckConstraint("status IN ('open', 'converted', 'expired')", name="status_allowed"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    items: Mapped[list[CartItem]] = relationship(back_populates="cart", cascade="all, delete-orphan")


class CartItem(TimestampMixin, Base):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "variant_id", name="uq_cart_items_cart_id_variant_id"),
        CheckConstraint("quantity > 0 AND quantity <= 20", name="quantity_allowed"),
    )


    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    cart_id: Mapped[UUID] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cart: Mapped[Cart] = relationship(back_populates="items")
    variant: Mapped["Variant"] = relationship()
