"""Persist garment sizes, cart coupons and guest support ownership."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("variants", sa.Column("size", sa.String(30)))
    op.add_column("carts", sa.Column("coupon_code", sa.String(100)))
    op.alter_column("support_cases", "customer_id", nullable=True)
    op.add_column("support_cases", sa.Column("guest_email", sa.String(320)))
    op.add_column("support_cases", sa.Column("token_hash", sa.String(64)))


def downgrade():
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM support_cases WHERE customer_id IS NULL"))
    if count:
        raise RuntimeError("Guest support cases must be reconciled before downgrade")
    op.drop_column("support_cases", "token_hash")
    op.drop_column("support_cases", "guest_email")
    op.alter_column("support_cases", "customer_id", nullable=False)
    op.drop_column("carts", "coupon_code")
    op.drop_column("variants", "size")
