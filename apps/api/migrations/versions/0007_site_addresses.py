"""Each route's yard and disposal site keep the address they were found by.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("routes", sa.Column("yard_address", sa.String(200), nullable=True))
    op.add_column("routes", sa.Column("disposal_address", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "disposal_address")
    op.drop_column("routes", "yard_address")
