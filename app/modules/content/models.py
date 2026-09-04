from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class StorefrontSetting(TimestampMixin, Base):
    __tablename__ = "storefront_settings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class NavigationItem(TimestampMixin, Base):
    __tablename__ = "navigation_items"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("navigation_items.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ContentPage(TimestampMixin, Base):
    __tablename__ = "content_pages"
    __table_args__ = (CheckConstraint("kind IN ('page', 'story')", name="kind_allowed"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hero_url: Mapped[str | None] = mapped_column(String(2000))
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ConsentRecord(TimestampMixin, Base):
    __tablename__ = "consent_records"
    __table_args__ = (CheckConstraint("action IN ('granted', 'withdrawn')", name="action_allowed"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="storefront")
