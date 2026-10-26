"""The initial tables of ADR-0004.

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLE = postgresql.ENUM("owner", "planner", "viewer", name="role", create_type=False)
STOP_STATE = postgresql.ENUM("snapped", "review", "rejected", name="stop_state", create_type=False)
RUN_STATE = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", name="run_state", create_type=False
)


def _point() -> Geography:
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def _id() -> sa.Column[sa.Uuid]:
    return sa.Column("id", sa.Uuid(), primary_key=True)


def _created(name: str = "created_at") -> sa.Column[sa.DateTime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _org() -> sa.Column[sa.Uuid]:
    return sa.Column(
        "org_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    bind = op.get_bind()
    for enum in (ROLE, STOP_STATE, RUN_STATE):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations", _id(), sa.Column("name", sa.String(200), nullable=False), _created()
    )
    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        _created(),
    )
    op.create_table(
        "memberships",
        _id(),
        _org(),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", ROLE, nullable=False),
        _created(),
        sa.UniqueConstraint("org_id", "user_id"),
    )
    op.create_table(
        "login_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created("last_seen_at"),
    )
    op.create_table(
        "routes",
        _id(),
        _org(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("capacity_carts", sa.Integer()),
        sa.Column("max_route_hours", sa.Float()),
        sa.Column("yard", _point(), nullable=False),
        sa.Column("disposal", _point(), nullable=False),
        _created(),
    )
    op.create_table(
        "uploads",
        _id(),
        _org(),
        sa.Column(
            "route_id", sa.Uuid(), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        _created(),
    )
    op.create_table(
        "stops",
        _id(),
        _org(),
        sa.Column(
            "upload_id", sa.Uuid(), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("stop_id", sa.String(100), nullable=False),
        sa.Column("current_sequence", sa.Integer(), nullable=False),
        sa.Column("current_route_id", sa.String(100)),
        sa.Column("location", _point(), nullable=False),
        sa.Column("street", sa.String(200)),
        sa.Column("state", STOP_STATE, nullable=False),
        sa.Column("segment_id", sa.String(100)),
        sa.Column("curb_side", sa.String(5)),
        sa.Column("review_reason", sa.String(100)),
        sa.UniqueConstraint("upload_id", "stop_id"),
    )
    op.create_table(
        "runs",
        _id(),
        _org(),
        sa.Column(
            "route_id", sa.Uuid(), sa.ForeignKey("routes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "upload_id", sa.Uuid(), sa.ForeignKey("uploads.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("state", RUN_STATE, nullable=False),
        sa.Column("trucks", sa.Integer(), nullable=False),
        sa.Column("objective", sa.String(40), nullable=False),
        sa.Column("osm_snapshot", sa.String(40)),
        sa.Column("solver_version", sa.String(40)),
        sa.Column("failure_reason", sa.String(500)),
        _created(),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "run_results",
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        _org(),
        sa.Column("result", postgresql.JSONB(), nullable=False),
    )
    for table in ("memberships", "routes", "uploads", "stops", "runs", "run_results"):
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_stops_upload_id", "stops", ["upload_id"])


def downgrade() -> None:
    for table in (
        "run_results",
        "runs",
        "stops",
        "uploads",
        "routes",
        "sessions",
        "login_tokens",
        "memberships",
        "users",
        "organizations",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in (RUN_STATE, STOP_STATE, ROLE):
        enum.drop(bind, checkfirst=True)
