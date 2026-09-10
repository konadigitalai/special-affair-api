from uuid import UUID
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class SupportCase(TimestampMixin, Base):
    __tablename__ = "support_cases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), index=True)
    guest_email: Mapped[str | None] = mapped_column(String(320))
    token_hash: Mapped[str | None] = mapped_column(String(64))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id"))
    subject: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), default="open")


class CaseMessage(TimestampMixin, Base):
    __tablename__ = "case_messages"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
