from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class Checkout(TimestampMixin, Base):
    __tablename__ = "checkouts"
    __table_args__ = (CheckConstraint("status IN ('open', 'awaiting_payment', 'completed', 'expired')", name="status_allowed"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    cart_id: Mapped[UUID] = mapped_column(ForeignKey("carts.id", ondelete="RESTRICT"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False)
    shipping_address: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shipping_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class IdempotencyKey(TimestampMixin, Base):
    __tablename__ = "idempotency_keys"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
