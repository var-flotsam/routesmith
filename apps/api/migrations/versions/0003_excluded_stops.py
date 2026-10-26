"""A planner can leave a stop out of every run.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE stop_state ADD VALUE IF NOT EXISTS 'excluded'")


def downgrade() -> None:
    # Postgres cannot drop an enum value: excluded stops go back to review, and the type
    # is rebuilt without it.
    op.execute("UPDATE stops SET state = 'review' WHERE state = 'excluded'")
    op.execute("ALTER TYPE stop_state RENAME TO stop_state_with_excluded")
    op.execute("CREATE TYPE stop_state AS ENUM ('snapped', 'review', 'rejected')")
    op.execute("ALTER TABLE stops ALTER COLUMN state TYPE stop_state USING state::text::stop_state")
    op.execute("DROP TYPE stop_state_with_excluded")
