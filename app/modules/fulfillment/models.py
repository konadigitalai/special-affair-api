from uuid import UUID
from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class Fulfillment(TimestampMixin, Base):
    __tablename__ = "fulfillments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="allocated")


class Shipment(TimestampMixin, Base):
    __tablename__ = "shipments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    fulfillment_id: Mapped[UUID] = mapped_column(
        ForeignKey("fulfillments.id"), index=True
    )
    carrier: Mapped[str] = mapped_column(String(100))
    tracking_number: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="dispatched")


class ShipmentItem(TimestampMixin, Base):
    __tablename__ = "shipment_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    shipment_id: Mapped[UUID] = mapped_column(ForeignKey("shipments.id"), index=True)
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_items.id"))
    quantity: Mapped[int] = mapped_column(Integer)
