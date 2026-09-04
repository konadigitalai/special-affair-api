"""Create the catalog domain tables.

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "products",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="ck_products_status_allowed"),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
    )
    op.create_index("ix_products_status", "products", ["status"])

    op.create_table(
        "categories",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("parent_id", uuid_type, nullable=True),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["categories.id"], name="fk_categories_parent_id_categories", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])

    op.create_table(
        "collections",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_collections"),
        sa.UniqueConstraint("slug", name="uq_collections_slug"),
    )

    op.create_table(
        "variants",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("product_id", uuid_type, nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(250), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("position >= 0", name="ck_variants_position_nonnegative"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_variants_status_allowed"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_variants_product_id_products", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_variants"),
        sa.UniqueConstraint("product_id", "slug", name="uq_variants_product_id_slug"),
        sa.UniqueConstraint("sku", name="uq_variants_sku"),
    )
    op.create_index("ix_variants_product_id", "variants", ["product_id"])

    op.create_table(
        "media_metadata",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("product_id", uuid_type, nullable=False),
        sa.Column("variant_id", uuid_type, nullable=True),
        sa.Column("media_type", sa.String(20), server_default="image", nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("public_url", sa.String(2000), nullable=True),
        sa.Column("alt_text", sa.String(500), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.CheckConstraint("media_type IN ('image', 'video', 'document')", name="ck_media_metadata_media_type_allowed"),
        sa.CheckConstraint("position >= 0", name="ck_media_metadata_position_nonnegative"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_media_metadata_product_id_products", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["variants.id"], name="fk_media_metadata_variant_id_variants", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_media_metadata"),
        sa.UniqueConstraint("storage_key", name="uq_media_metadata_storage_key"),
    )
    op.create_index("ix_media_metadata_product_id", "media_metadata", ["product_id"])
    op.create_index("ix_media_metadata_variant_id", "media_metadata", ["variant_id"])

    op.create_table(
        "product_categories",
        sa.Column("product_id", uuid_type, nullable=False),
        sa.Column("category_id", uuid_type, nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], name="fk_product_categories_category_id_categories", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_product_categories_product_id_products", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("product_id", "category_id", name="pk_product_categories"),
    )
    op.create_table(
        "product_collections",
        sa.Column("product_id", uuid_type, nullable=False),
        sa.Column("collection_id", uuid_type, nullable=False),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], name="fk_product_collections_collection_id_collections", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_product_collections_product_id_products", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("product_id", "collection_id", name="pk_product_collections"),
    )


def downgrade() -> None:
    op.drop_table("product_collections")
    op.drop_table("product_categories")
    op.drop_table("media_metadata")
    op.drop_table("variants")
    op.drop_table("collections")
    op.drop_table("categories")
    op.drop_table("products")
