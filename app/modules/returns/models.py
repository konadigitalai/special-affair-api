from uuid import UUID
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class Return(TimestampMixin, Base):
    __tablename__ = "returns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','approved','rejected','in_transit','received','inspected','refund_pending','refunded','refund_failed')",
            name="status_allowed",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="requested")
    reason: Mapped[str] = mapped_column(String(1000))


class ReturnItem(TimestampMixin, Base):
    __tablename__ = "return_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    return_id: Mapped[UUID] = mapped_column(ForeignKey("returns.id"), index=True)
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id"))
    quantity: Mapped[int] = mapped_column(Integer)


class Refund(TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "status IN ('awaiting_approval','refund_pending','refunded','refund_failed','rejected')",
            name="status_allowed",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    payment_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_attempts.id"), index=True
    )
    return_id: Mapped[UUID | None] = mapped_column(ForeignKey("returns.id"))
    approval_id: Mapped[UUID | None] = mapped_column(ForeignKey("approvals.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(30))
    requested_by: Mapped[str] = mapped_column(String(200))
    provider_reference: Mapped[str | None] = mapped_column(String(200))
