"""add users and friendships

Revision ID: 2cc76b9122b9
Revises: 22b8206bab6a
Create Date: 2026-09-17

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2cc76b9122b9"
down_revision: str | Sequence[str] | None = "22b8206bab6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("username", sa.String(length=24), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "friendships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("requester_id", sa.UUID(), nullable=False),
        sa.Column("addressee_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requester_id"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["addressee_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendships_pair"),
    )
    op.create_index("ix_friendships_requester", "friendships", ["requester_id"], unique=False)
    op.create_index("ix_friendships_addressee", "friendships", ["addressee_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_friendships_addressee", table_name="friendships")
    op.drop_index("ix_friendships_requester", table_name="friendships")
    op.drop_table("friendships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
