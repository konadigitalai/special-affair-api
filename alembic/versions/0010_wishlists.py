"""Persist guest and account wishlists."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("wishlists", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id"), unique=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("wishlist_items", sa.Column("wishlist_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("wishlists.id", ondelete="CASCADE"), primary_key=True), sa.Column("variant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="CASCADE"), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

def downgrade():
    op.drop_table("wishlist_items")
    op.drop_table("wishlists")
