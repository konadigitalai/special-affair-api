"""Create guest cart, checkout, order, and payment tables.

Revision ID: 0005
Revises: 0004
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def ts() -> tuple[sa.Column, sa.Column]:
    return (sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def upgrade() -> None:
    u = postgresql.UUID(as_uuid=True)
    op.create_table("carts", sa.Column("id", u, primary_key=True), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("status", sa.String(20), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("version", sa.Integer, nullable=False), *ts(), sa.CheckConstraint("status IN ('open', 'converted', 'expired')", name=op.f("ck_carts_status_allowed")))
    op.create_table("cart_items", sa.Column("id", u, primary_key=True), sa.Column("cart_id", u, sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False), sa.Column("variant_id", u, sa.ForeignKey("variants.id", ondelete="RESTRICT"), nullable=False), sa.Column("quantity", sa.Integer, nullable=False), sa.Column("unit_price_minor", sa.BigInteger, nullable=False), sa.Column("currency", sa.String(3), nullable=False), *ts(), sa.CheckConstraint("quantity > 0 AND quantity <= 20", name=op.f("ck_cart_items_quantity_allowed")), sa.UniqueConstraint("cart_id", "variant_id", name=op.f("uq_cart_items_cart_id_variant_id")))
    op.create_index(op.f("ix_cart_items_cart_id"), "cart_items", ["cart_id"])
    op.create_index(op.f("ix_cart_items_variant_id"), "cart_items", ["variant_id"])
    op.create_table("checkouts", sa.Column("id", u, primary_key=True), sa.Column("cart_id", u, sa.ForeignKey("carts.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("status", sa.String(30), nullable=False), sa.Column("email", sa.String(320), nullable=False), sa.Column("phone", sa.String(30), nullable=False), sa.Column("shipping_address", postgresql.JSONB, nullable=False), sa.Column("subtotal_minor", sa.BigInteger, nullable=False), sa.Column("shipping_minor", sa.BigInteger, nullable=False), sa.Column("tax_minor", sa.BigInteger, nullable=False), sa.Column("total_minor", sa.BigInteger, nullable=False), sa.Column("currency", sa.String(3), nullable=False), *ts(), sa.CheckConstraint("status IN ('open', 'awaiting_payment', 'completed', 'expired')", name=op.f("ck_checkouts_status_allowed")))
    op.create_index(op.f("ix_checkouts_cart_id"), "checkouts", ["cart_id"], unique=True)
    op.create_table("idempotency_keys", sa.Column("key", sa.String(200), primary_key=True), sa.Column("operation", sa.String(100), nullable=False), sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("resource_id", u, nullable=False), *ts())
    op.create_table("orders", sa.Column("id", u, primary_key=True), sa.Column("checkout_id", u, sa.ForeignKey("checkouts.id", ondelete="RESTRICT"), nullable=False, unique=True), sa.Column("order_number", sa.String(30), nullable=False, unique=True), sa.Column("order_token_hash", sa.String(64), nullable=False, unique=True), sa.Column("email", sa.String(320), nullable=False), sa.Column("phone", sa.String(30), nullable=False), sa.Column("shipping_address", postgresql.JSONB, nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("payment_method", sa.String(20), nullable=False), sa.Column("subtotal_minor", sa.BigInteger, nullable=False), sa.Column("shipping_minor", sa.BigInteger, nullable=False), sa.Column("tax_minor", sa.BigInteger, nullable=False), sa.Column("total_minor", sa.BigInteger, nullable=False), sa.Column("currency", sa.String(3), nullable=False), *ts(), sa.CheckConstraint("status IN ('pending_payment', 'confirmed', 'cancelled', 'fulfilled')", name=op.f("ck_orders_status_allowed")))
    op.create_index(op.f("ix_orders_email"), "orders", ["email"])
    op.create_index(op.f("ix_orders_order_number"), "orders", ["order_number"], unique=True)
    op.create_table("order_items", sa.Column("id", u, primary_key=True), sa.Column("order_id", u, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False), sa.Column("variant_id", u, nullable=False), sa.Column("product_name", sa.String(250), nullable=False), sa.Column("variant_name", sa.String(250), nullable=False), sa.Column("sku", sa.String(100), nullable=False), sa.Column("quantity", sa.Integer, nullable=False), sa.Column("unit_price_minor", sa.BigInteger, nullable=False), sa.Column("line_total_minor", sa.BigInteger, nullable=False), sa.Column("currency", sa.String(3), nullable=False), *ts())
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"])
    op.create_table("payment_attempts", sa.Column("id", u, primary_key=True), sa.Column("order_id", u, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False), sa.Column("provider", sa.String(50), nullable=False), sa.Column("method", sa.String(20), nullable=False), sa.Column("provider_reference", sa.String(200), nullable=False, unique=True), sa.Column("status", sa.String(20), nullable=False), sa.Column("amount_minor", sa.BigInteger, nullable=False), sa.Column("currency", sa.String(3), nullable=False), *ts(), sa.CheckConstraint("status IN ('initiated', 'pending', 'captured', 'failed')", name=op.f("ck_payment_attempts_status_allowed")))
    op.create_index(op.f("ix_payment_attempts_order_id"), "payment_attempts", ["order_id"])


def downgrade() -> None:
    for table in ("payment_attempts", "order_items", "orders", "idempotency_keys", "checkouts", "cart_items", "carts"):
        op.drop_table(table)
