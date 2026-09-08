from datetime import datetime
from uuid import UUID
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class Promotion(TimestampMixin, Base):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint("percent_off > 0 AND percent_off <= 100", name="percent_valid"),
        CheckConstraint("ends_at > starts_at", name="window_valid"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200))
    percent_off: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="draft")


class Coupon(TimestampMixin, Base):
    __tablename__ = "coupons"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    promotion_id: Mapped[UUID] = mapped_column(ForeignKey("promotions.id"))
    code: Mapped[str] = mapped_column(String(100), unique=True)
