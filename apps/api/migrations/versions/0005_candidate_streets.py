"""A stop in review keeps its candidate streets drawn, for the review map.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "stops",
        sa.Column("candidate_streets", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("stops", "candidate_streets")
