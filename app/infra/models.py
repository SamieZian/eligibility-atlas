"""SQLAlchemy ORM models for atlas_db."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Date,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    employer_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    subgroup_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    member_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    relationship: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date] = mapped_column(Date, nullable=False)
    txn_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    txn_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_file_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    source_segment_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("enr_member_inforce", "tenant_id", "member_id", "valid_from"),
        Index("enr_employer_active", "tenant_id", "employer_id", "status", "valid_from"),
    )


class ProcessedSegment(Base):
    __tablename__ = "processed_segments"

    segment_key: Mapped[str] = mapped_column(Text, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Saga(Base):
    __tablename__ = "sagas"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
