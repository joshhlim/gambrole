"""users.deleted_at

Revision ID: a9c4e2f7b1d3
Revises: f1b8d3e5a7c9
Create Date: 2026-10-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c4e2f7b1d3"
down_revision: str | Sequence[str] | None = "f1b8d3e5a7c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable, no default: expand-only, safe while the old code still runs.
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "deleted_at")
