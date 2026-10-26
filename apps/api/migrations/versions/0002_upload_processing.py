"""Uploads are read and snapped by the worker; stops keep where they snapped.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPLOAD_STATE = postgresql.ENUM(
    "processing", "ready", "failed", name="upload_state", create_type=False
)


def upgrade() -> None:
    UPLOAD_STATE.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "uploads",
        sa.Column("state", UPLOAD_STATE, nullable=False, server_default="processing"),
    )
    op.alter_column("uploads", "state", server_default=None)
    op.add_column(
        "uploads",
        sa.Column("rejected_rows", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column("uploads", sa.Column("osm_snapshot", sa.String(40)))
    op.add_column("uploads", sa.Column("failure_reason", sa.String(500)))
    op.add_column("stops", sa.Column("required_direction", sa.String(8)))
    op.add_column("stops", sa.Column("distance_along_m", sa.Float()))
    op.add_column("stops", sa.Column("distance_from_centerline_m", sa.Float()))
    op.add_column("stops", sa.Column("review_detail", sa.String(500)))
    op.add_column(
        "stops",
        sa.Column("candidate_segment_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    for column in (
        "candidate_segment_ids",
        "review_detail",
        "distance_from_centerline_m",
        "distance_along_m",
        "required_direction",
    ):
        op.drop_column("stops", column)
    for column in ("failure_reason", "osm_snapshot", "rejected_rows", "state"):
        op.drop_column("uploads", column)
    UPLOAD_STATE.drop(op.get_bind(), checkfirst=True)
