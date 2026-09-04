from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class Order(TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("status IN ('pending_payment', 'confirmed', 'cancelled', 'fulfilled')", name="status_allowed"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    checkout_id: Mapped[UUID] = mapped_column(ForeignKey("checkouts.id", ondelete="RESTRICT"), unique=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    order_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str] = mapped_column(String(30))
    shipping_address: Mapped[dict[str, object]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(30))
    payment_method: Mapped[str] = mapped_column(String(20))
    subtotal_minor: Mapped[int] = mapped_column(BigInteger)
    shipping_minor: Mapped[int] = mapped_column(BigInteger)
    tax_minor: Mapped[int] = mapped_column(BigInteger)
    total_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    variant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    product_name: Mapped[str] = mapped_column(String(250))
    variant_name: Mapped[str] = mapped_column(String(250))
    sku: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger)
    line_total_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))

