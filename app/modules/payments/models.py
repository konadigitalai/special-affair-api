from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    Boolean,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class PaymentAttempt(TimestampMixin, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('initiated','pending','requires_action','authorized','captured','failed','expired','voided','partially_refunded','refunded')",
            name="status_allowed",
        ),
        CheckConstraint(
            "captured_amount_minor >= 0 AND refunded_amount_minor >= 0 AND refunded_amount_minor <= captured_amount_minor AND captured_amount_minor <= amount_minor",
            name="amounts_valid",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(20))
    provider_reference: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    captured_amount_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    refunded_amount_minor: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )


class WebhookInbox(TimestampMixin, Base):
    __tablename__ = "webhook_inbox"
    __table_args__ = (UniqueConstraint("provider", "provider_event_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    provider: Mapped[str] = mapped_column(String(50))
    provider_event_id: Mapped[str] = mapped_column(String(200))
    signature_verified: Mapped[bool] = mapped_column(Boolean)
    raw_payload: Mapped[dict] = mapped_column(JSONB)
    processing_error: Mapped[str | None] = mapped_column(String(200))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)


class PaymentTransaction(TimestampMixin, Base):
    __tablename__ = "payment_transactions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    payment_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_attempts.id"), index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
