"""Pure-domain bitemporal enrollment model. No I/O here — repository handles persistence.

Bitemporal rules:
- `valid_from`..`valid_to` is when coverage is true in reality.
- `txn_from`..`txn_to` is when the system believed that to be true.
- An in-force row is one where `txn_to = INFINITY`; history rows have `txn_to` < now.
- We never UPDATE a row's business fields; we close the current row (set txn_to)
  and INSERT a new row. This preserves an immutable audit trail and lets us
  answer "what did we believe on date X" queries.

Terminology:
- "Close" a row: set txn_to = now(). The row becomes history.
- "Open" a new row: insert with txn_from = now(), txn_to = INFINITY.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

INFINITY_DATE = date.max  # 9999-12-31 used as open-ended valid_to
INFINITY_TS = datetime.max.replace(tzinfo=timezone.utc)


class Status(str, Enum):
    ACTIVE = "active"
    TERMED = "termed"
    PENDING = "pending"


class Relationship(str, Enum):
    SUBSCRIBER = "subscriber"
    SPOUSE = "spouse"
    CHILD = "child"
    DEPENDENT = "dependent"


@dataclass
class EnrollmentSegment:
    """One row in the bitemporal enrollments table."""

    id: UUID
    tenant_id: UUID
    employer_id: UUID
    subgroup_id: UUID | None
    plan_id: UUID
    member_id: UUID
    relationship: Relationship
    status: Status
    valid_from: date
    valid_to: date
    txn_from: datetime
    txn_to: datetime
    source_file_id: UUID | None
    source_segment_ref: str | None
    version: int = 1

    @property
    def is_in_force(self) -> bool:
        return self.txn_to >= INFINITY_TS.replace(tzinfo=self.txn_to.tzinfo)

    def overlaps(self, other_from: date, other_to: date) -> bool:
        return not (self.valid_to < other_from or self.valid_from > other_to)


@dataclass
class AddCommand:
    tenant_id: UUID
    employer_id: UUID
    subgroup_id: UUID | None
    plan_id: UUID
    member_id: UUID
    relationship: Relationship
    valid_from: date
    valid_to: date = INFINITY_DATE
    source_file_id: UUID | None = None
    source_segment_ref: str | None = None


@dataclass
class TerminateCommand:
    tenant_id: UUID
    member_id: UUID
    plan_id: UUID
    valid_to: date
    source_file_id: UUID | None = None
    source_segment_ref: str | None = None


@dataclass
class CorrectionCommand:
    """Retroactive correction — close current segment(s) and open corrected one(s)."""

    tenant_id: UUID
    member_id: UUID
    plan_id: UUID
    new_valid_from: date
    new_valid_to: date
    employer_id: UUID
    subgroup_id: UUID | None
    relationship: Relationship
    source_file_id: UUID | None = None
    source_segment_ref: str | None = None


@dataclass
class Timeline:
    """Current (in-force) view of a member's enrollments on a given plan."""

    segments: list[EnrollmentSegment] = field(default_factory=list)

    def in_force(self) -> list[EnrollmentSegment]:
        return [s for s in self.segments if s.is_in_force]

    def overlaps_with(self, new_from: date, new_to: date, plan_id: UUID) -> list[EnrollmentSegment]:
        return [
            s
            for s in self.in_force()
            if s.plan_id == plan_id
            and s.status == Status.ACTIVE
            and s.overlaps(new_from, new_to)
        ]


def new_id() -> UUID:
    return uuid4()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
