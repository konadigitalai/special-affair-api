from uuid import UUID

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class AuditEntry(TimestampMixin, Base):
    __tablename__ = "audit_ledger"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    actor_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[UUID] = mapped_column(index=True)
    before_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    after_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(200))
