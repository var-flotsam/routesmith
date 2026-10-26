"""The database tables (ADR-0004). Every customer-owned row carries `org_id`."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _point() -> Geography:
    # No spatial index yet: nothing queries by location until the map views (phase 5).
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _org() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)


class Role(StrEnum):
    OWNER = "owner"
    PLANNER = "planner"
    VIEWER = "viewer"


class StopState(StrEnum):
    SNAPPED = "snapped"
    REVIEW = "review"
    REJECTED = "rejected"
    EXCLUDED = "excluded"  # the planner left it out of every run


class UploadState(StrEnum):
    PROCESSING = "processing"  # waiting for the worker to read and snap it
    READY = "ready"
    FAILED = "failed"


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = _id()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _id()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lower-case
    created_at: Mapped[datetime] = _created()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id"),)
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda e: [m.value for m in e])
    )
    created_at: Mapped[datetime] = _created()


class LoginToken(Base):
    __tablename__ = "login_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256, hex
    email: Mapped[str] = mapped_column(String(320))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256, hex
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = _created()


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org()
    name: Mapped[str] = mapped_column(String(200))
    capacity_carts: Mapped[int | None]
    max_route_hours: Mapped[float | None]
    # PostGIS points; GeoAlchemy2 gives them no Python type.
    yard: Mapped[Any] = mapped_column(_point())
    disposal: Mapped[Any] = mapped_column(_point())
    created_at: Mapped[datetime] = _created()


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org()
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(255))
    state: Mapped[UploadState] = mapped_column(
        Enum(UploadState, name="upload_state", values_callable=lambda e: [m.value for m in e])
    )
    rows_read: Mapped[int]
    rows_rejected: Mapped[int]
    # Rows the reader could not use: [{"line": n, "reason": "..."}].
    rejected_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    osm_snapshot: Mapped[str | None] = mapped_column(String(40))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()


class Stop(Base):
    __tablename__ = "stops"
    __table_args__ = (UniqueConstraint("upload_id", "stop_id"),)
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org()
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="CASCADE"), index=True
    )
    stop_id: Mapped[str] = mapped_column(String(100))
    current_sequence: Mapped[int]
    current_route_id: Mapped[str | None] = mapped_column(String(100))
    # A PostGIS point, untyped in GeoAlchemy2; none for an address the geocoder could not place.
    location: Mapped[Any | None] = mapped_column(_point(), nullable=True)
    street: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[StopState] = mapped_column(
        Enum(StopState, name="stop_state", values_callable=lambda e: [m.value for m in e])
    )
    # Where the stop snapped, kept so a run solves exactly what the planner reviewed.
    segment_id: Mapped[str | None] = mapped_column(String(100))
    curb_side: Mapped[str | None] = mapped_column(String(5))  # side of the segment, forward
    required_direction: Mapped[str | None] = mapped_column(String(8))
    distance_along_m: Mapped[float | None]
    distance_from_centerline_m: Mapped[float | None]
    review_reason: Mapped[str | None] = mapped_column(String(100))
    review_detail: Mapped[str | None] = mapped_column(String(500))
    # The streets a stop in review could belong to, for the planner to choose from.
    candidate_segment_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    # The same streets drawn: [{"segment_id", "name", "curb_side", "line": [[lon, lat], ...]}].
    candidate_streets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = _id()
    org_id: Mapped[uuid.UUID] = _org()
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"))
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="CASCADE"))
    state: Mapped[RunState] = mapped_column(
        Enum(RunState, name="run_state", values_callable=lambda e: [m.value for m in e])
    )
    trucks: Mapped[int]
    objective: Mapped[str] = mapped_column(String(40))
    osm_snapshot: Mapped[str | None] = mapped_column(String(40))
    solver_version: Mapped[str | None] = mapped_column(String(40))
    failure_reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunResult(Base):
    __tablename__ = "run_results"
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = _org()
    # The solver output, ready for JSON: scorecards, orders, unserved stops, bound and gap.
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
