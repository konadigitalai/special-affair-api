"""Add conversation ownership tokens without removing legacy data.

Existing unowned conversations cannot be resumed; clients start new sessions.
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "copilot_sessions", sa.Column("token_hash", sa.String(64), nullable=True)
    )


def downgrade():
    # Preserve ownership hashes on application rollback; dropping them would weaken access control.
    raise RuntimeError(
        "Keep ownership hashes on rollback; use a reviewed forward migration"
    )
