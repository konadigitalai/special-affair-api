from uuid import UUID
from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected')", name="status_allowed"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[UUID] = mapped_column(index=True)
    requested_by: Mapped[str] = mapped_column(String(200))
    decided_by: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="pending")
