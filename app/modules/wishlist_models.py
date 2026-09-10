from uuid import UUID
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, uuid7


class Wishlist(TimestampMixin, Base):
    __tablename__ = "wishlists"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"), unique=True)


class WishlistItem(TimestampMixin, Base):
    __tablename__ = "wishlist_items"
    wishlist_id: Mapped[UUID] = mapped_column(ForeignKey("wishlists.id", ondelete="CASCADE"), primary_key=True)
    variant_id: Mapped[UUID] = mapped_column(ForeignKey("variants.id", ondelete="CASCADE"), primary_key=True)
