"""Create Shopping Copilot persistence tables.

Revision ID: 0004
Revises: 0003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "copilot_sessions",
        sa.Column("id", uuid, nullable=False),
        sa.Column("customer_id", uuid, nullable=True),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_copilot_sessions"),
    )
    op.create_index("ix_copilot_sessions_customer_id", "copilot_sessions", ["customer_id"])
    op.create_table(
        "copilot_messages",
        sa.Column("id", uuid, nullable=False),
        sa.Column("session_id", uuid, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        *timestamps(),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_copilot_messages_role_allowed"),
        sa.ForeignKeyConstraint(["session_id"], ["copilot_sessions.id"], name="fk_copilot_messages_session_id_copilot_sessions", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_copilot_messages"),
    )
    op.create_index("ix_copilot_messages_session_id", "copilot_messages", ["session_id"])
    op.create_table(
        "product_embeddings",
        sa.Column("id", uuid, nullable=False),
        sa.Column("product_id", uuid, nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.JSONB(), nullable=False),
        sa.Column("embedding_model", sa.String(150), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_product_embeddings_product_id_products", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_product_embeddings"),
        sa.UniqueConstraint("product_id", name="uq_product_embeddings_product_id"),
    )
    op.create_index("ix_product_embeddings_product_id", "product_embeddings", ["product_id"])


def downgrade() -> None:
    op.drop_table("product_embeddings")
    op.drop_table("copilot_messages")
    op.drop_table("copilot_sessions")
