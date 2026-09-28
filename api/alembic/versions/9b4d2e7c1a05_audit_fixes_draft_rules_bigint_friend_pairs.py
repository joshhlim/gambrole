"""draft rules on rooms, 64-bit settlement amounts, one friendship per pair

Revision ID: 9b4d2e7c1a05
Revises: 2cc76b9122b9
Create Date: 2026-09-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9b4d2e7c1a05"
down_revision: str | Sequence[str] | None = "2cc76b9122b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "rooms", sa.Column("draft_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.alter_column(
        "settlements",
        "amount_cents",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )

    # Collapse any pair that already has a row in each direction before the
    # unordered-pair index can exist. Two rows for one pair only ever meant
    # "these two want to be friends" (a mutual request, or an accept that
    # raced a request), so keep the oldest row and mark it accepted.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER w AS rn,
                   count(*) OVER (
                       PARTITION BY least(requester_id, addressee_id),
                                    greatest(requester_id, addressee_id)
                   ) AS cnt
            FROM friendships
            WINDOW w AS (
                PARTITION BY least(requester_id, addressee_id),
                             greatest(requester_id, addressee_id)
                ORDER BY created_at, id
            )
        )
        UPDATE friendships
        SET status = 'accepted', responded_at = coalesce(responded_at, now())
        WHERE id IN (SELECT id FROM ranked WHERE rn = 1 AND cnt > 1)
        """
    )
    op.execute(
        """
        DELETE FROM friendships
        WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY least(requester_id, addressee_id),
                                 greatest(requester_id, addressee_id)
                    ORDER BY created_at, id
                ) AS rn
                FROM friendships
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.create_index(
        "uq_friendships_unordered_pair",
        "friendships",
        [
            sa.text("least(requester_id, addressee_id)"),
            sa.text("greatest(requester_id, addressee_id)"),
        ],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_friendships_unordered_pair", table_name="friendships")
    op.alter_column(
        "settlements",
        "amount_cents",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
    )
    op.drop_column("rooms", "draft_rules")
