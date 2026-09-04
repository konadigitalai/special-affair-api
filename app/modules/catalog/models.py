from __future__ import annotations

from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, uuid7


product_categories = Table(
    "product_categories",
    Base.metadata,
    Column("product_id", PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("category_id", PGUUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
)

product_collections = Table(
    "product_collections",
    Base.metadata,
    Column("product_id", PGUUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True),
    Column("collection_id", PGUUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
)


class Product(TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="status_allowed"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    materials: Mapped[str | None] = mapped_column(Text)
    care: Mapped[str | None] = mapped_column(Text)
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    variants: Mapped[list[Variant]] = relationship(back_populates="product", order_by="Variant.position")
    categories: Mapped[list[Category]] = relationship(secondary=product_categories, back_populates="products")
    collections: Mapped[list[Collection]] = relationship(secondary=product_collections, back_populates="products")
    media: Mapped[list[MediaMetadata]] = relationship(back_populates="product", order_by="MediaMetadata.position")


class Variant(TimestampMixin, Base):
    __tablename__ = "variants"
    __table_args__ = (
        UniqueConstraint("product_id", "slug", name="uq_variants_product_id_slug"),
        CheckConstraint("status IN ('active', 'archived')", name="status_allowed"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    colour: Mapped[str | None] = mapped_column(String(100), index=True)
    material: Mapped[str | None] = mapped_column(String(150), index=True)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    product: Mapped[Product] = relationship(back_populates="variants")
    media: Mapped[list[MediaMetadata]] = relationship(back_populates="variant", order_by="MediaMetadata.position")


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"), index=True)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    products: Mapped[list[Product]] = relationship(secondary=product_categories, back_populates="categories")


class Collection(TimestampMixin, Base):
    __tablename__ = "collections"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    products: Mapped[list[Product]] = relationship(secondary=product_collections, back_populates="collections")


class MediaMetadata(TimestampMixin, Base):
    __tablename__ = "media_metadata"
    __table_args__ = (
        CheckConstraint("media_type IN ('image', 'video', 'document')", name="media_type_allowed"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_id: Mapped[UUID | None] = mapped_column(ForeignKey("variants.id", ondelete="CASCADE"), index=True)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image", server_default="image")
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    public_url: Mapped[str | None] = mapped_column(String(2000))
    alt_text: Mapped[str | None] = mapped_column(String(500))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    product: Mapped[Product] = relationship(back_populates="media")
    variant: Mapped[Variant | None] = relationship(back_populates="media")
