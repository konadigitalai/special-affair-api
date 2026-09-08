from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, uuid7


class Location(TimestampMixin, Base):
    __tablename__ = "locations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class InventoryItem(TimestampMixin, Base):
    __tablename__ = "inventory_items"
    __table_args__ = (
        UniqueConstraint("variant_id", "location_id"),
        CheckConstraint(
            "on_hand >= 0 AND reserved >= 0 AND safety_stock >= 0 AND on_hand >= reserved + safety_stock",
            name="stock_nonnegative",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id"), index=True)
    location_id: Mapped[UUID] = mapped_column(ForeignKey("locations.id"))
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved - self.safety_stock


class StockMovement(TimestampMixin, Base):
    __tablename__ = "stock_movements"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    inventory_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_items.id"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    actor_id: Mapped[str] = mapped_column(String(200))


class InventoryReservation(TimestampMixin, Base):
    __tablename__ = "inventory_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "status IN ('held','committed','released','expired','consumed')",
            name="status_allowed",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    inventory_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("inventory_items.id"), index=True
    )
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="held")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
