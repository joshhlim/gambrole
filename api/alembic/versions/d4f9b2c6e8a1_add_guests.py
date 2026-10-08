"""add guests

Revision ID: d4f9b2c6e8a1
Revises: c3e8a1f4d2b7
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f9b2c6e8a1"
down_revision: str | Sequence[str] | None = "c3e8a1f4d2b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "guests",
        sa.Column("guest_id", sa.UUID(), nullable=False),
        sa.Column("room_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=False),
        sa.Column("claimed_by", sa.UUID(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.room_id"]),
        sa.PrimaryKeyConstraint("guest_id"),
        sa.UniqueConstraint("claim_token"),
    )
    op.create_index("ix_guests_room_id", "guests", ["room_id"], unique=False)
    op.create_index("ix_guests_claimed_by", "guests", ["claimed_by"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_guests_claimed_by", table_name="guests")
    op.drop_index("ix_guests_room_id", table_name="guests")
    op.drop_table("guests")
