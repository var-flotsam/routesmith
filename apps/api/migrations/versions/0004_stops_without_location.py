"""A stop given by an address the geocoder could not place has no location.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26
"""

from alembic import op
from geoalchemy2 import Geography

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _point() -> Geography:
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.alter_column("stops", "location", existing_type=_point(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM stops WHERE location IS NULL")
    op.alter_column("stops", "location", existing_type=_point(), nullable=False)
