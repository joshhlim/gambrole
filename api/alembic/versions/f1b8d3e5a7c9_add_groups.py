"""groups and group_members; rooms.group_id

Revision ID: f1b8d3e5a7c9
Revises: e7a3c5d1f9b2
Create Date: 2026-10-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b8d3e5a7c9"
down_revision: str | Sequence[str] | None = "e7a3c5d1f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "groups",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("invite_code", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("group_id"),
        sa.UniqueConstraint("invite_code"),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.group_id"]),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"], unique=False)
    op.add_column("rooms", sa.Column("group_id", sa.UUID(), nullable=True))
    op.create_foreign_key("rooms_group_id_fkey", "rooms", "groups", ["group_id"], ["group_id"])
    op.create_index("ix_rooms_group_id", "rooms", ["group_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_rooms_group_id", table_name="rooms")
    op.drop_constraint("rooms_group_id_fkey", "rooms", type_="foreignkey")
    op.drop_column("rooms", "group_id")
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_table("groups")
