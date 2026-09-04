"""Add storefront catalog fields and content tables.

Revision ID: 0003
Revises: 0002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.add_column("products", sa.Column("materials", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("care", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("featured", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("variants", sa.Column("colour", sa.String(100), nullable=True))
    op.add_column("variants", sa.Column("material", sa.String(150), nullable=True))
    op.add_column("variants", sa.Column("price_minor", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("variants", sa.Column("currency", sa.String(3), server_default="INR", nullable=False))
    op.create_index("ix_variants_colour", "variants", ["colour"])
    op.create_index("ix_variants_material", "variants", ["material"])

    op.create_table(
        "storefront_settings",
        sa.Column("id", uuid, nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_storefront_settings"),
        sa.UniqueConstraint("key", name="uq_storefront_settings_key"),
    )
    op.create_table(
        "navigation_items",
        sa.Column("id", uuid, nullable=False),
        sa.Column("parent_id", uuid, nullable=True),
        sa.Column("label", sa.String(150), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["parent_id"], ["navigation_items.id"], name="fk_navigation_items_parent_id_navigation_items", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_navigation_items"),
    )
    op.create_index("ix_navigation_items_parent_id", "navigation_items", ["parent_id"])
    op.create_table(
        "content_pages",
        sa.Column("id", uuid, nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("hero_url", sa.String(2000), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("kind IN ('page', 'story')", name="ck_content_pages_kind_allowed"),
        sa.PrimaryKeyConstraint("id", name="pk_content_pages"),
        sa.UniqueConstraint("slug", name="uq_content_pages_slug"),
    )
    op.create_index("ix_content_pages_published", "content_pages", ["published"])
    op.create_table(
        "consent_records",
        sa.Column("id", uuid, nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        *timestamps(),
        sa.CheckConstraint("action IN ('granted', 'withdrawn')", name="ck_consent_records_action_allowed"),
        sa.PrimaryKeyConstraint("id", name="pk_consent_records"),
    )
    op.create_index("ix_consent_records_email", "consent_records", ["email"])


def downgrade() -> None:
    op.drop_table("consent_records")
    op.drop_table("content_pages")
    op.drop_table("navigation_items")
    op.drop_table("storefront_settings")
    op.drop_index("ix_variants_material", table_name="variants")
    op.drop_index("ix_variants_colour", table_name="variants")
    for column in ("currency", "price_minor", "material", "colour"):
        op.drop_column("variants", column)
    for column in ("featured", "care", "materials"):
        op.drop_column("products", column)
