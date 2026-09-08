from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    auth_subject: Mapped[str] = mapped_column(String(200), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))


class Address(TimestampMixin, Base):
    __tablename__ = "addresses"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    details: Mapped[dict] = mapped_column(JSONB)


from app.modules.content.models import ConsentRecord
