"""profiles, preferences and privacy on users; user_avatars

Revision ID: e7a3c5d1f9b2
Revises: d4f9b2c6e8a1
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7a3c5d1f9b2"
down_revision: str | Sequence[str] | None = "d4f9b2c6e8a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("bio", sa.String(length=160), nullable=True))
    op.add_column("users", sa.Column("city", sa.String(length=60), nullable=True))
    op.add_column("users", sa.Column("accent", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("avatar_version", sa.Integer(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "preferences",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "profile_visibility", sa.String(length=16), server_default="everyone", nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "stats_visibility", sa.String(length=16), server_default="friends", nullable=False
        ),
    )
    op.add_column(
        "users",
        sa.Column("searchable", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.create_table(
        "user_avatars",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_avatars")
    for column in (
        "searchable",
        "stats_visibility",
        "profile_visibility",
        "preferences",
        "avatar_version",
        "accent",
        "city",
        "bio",
    ):
        op.drop_column("users", column)
