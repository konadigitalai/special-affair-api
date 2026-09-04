from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class PaymentAttempt(TimestampMixin, Base):
    __tablename__ = "payment_attempts"
    __table_args__ = (CheckConstraint("status IN ('initiated', 'pending', 'captured', 'failed')", name="status_allowed"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    method: Mapped[str] = mapped_column(String(20))
    provider_reference: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
