"""Use-cases. Thin — domain rules live in `app.domain`."""
from __future__ import annotations

from uuid import UUID

from eligibility_common.errors import Codes, DomainError
from eligibility_common.events import Topics
from eligibility_common.outbox import emit
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enrollment import (
    AddCommand,
    CorrectionCommand,
    Relationship,
    Status,
    TerminateCommand,
    new_id,
)
from app.infra.repo import EnrollmentRepo


async def add_enrollment(s: AsyncSession, cmd: AddCommand, *, segment_key: str | None = None) -> UUID:
    repo = EnrollmentRepo(s)
    if segment_key and await repo.is_segment_processed(segment_key):
        # Duplicate 834 segment — treat as success (idempotent)
        raise DomainError(Codes.DUPLICATE_SEGMENT, "Segment already processed", http_status=200)

    timeline = await repo.load_timeline(cmd.tenant_id, cmd.member_id)
    if timeline.overlaps_with(cmd.valid_from, cmd.valid_to, cmd.plan_id):
        raise DomainError(
            Codes.ENROLLMENT_OVERLAP,
            "Member already has active coverage for this plan overlapping the requested period.",
        )
    new_eid = await repo.open_segment(
        tenant_id=cmd.tenant_id,
        employer_id=cmd.employer_id,
        subgroup_id=cmd.subgroup_id,
        plan_id=cmd.plan_id,
        member_id=cmd.member_id,
        relationship=cmd.relationship,
        status=Status.ACTIVE,
        valid_from=cmd.valid_from,
        valid_to=cmd.valid_to,
        source_file_id=cmd.source_file_id,
        source_segment_ref=cmd.source_segment_ref,
    )
    if segment_key:
        await repo.mark_segment_processed(segment_key)
    await emit(
        s,
        aggregate="enrollment",
        aggregate_id=new_eid,
        event_type="EnrollmentAdded",
        payload={
            "enrollment_id": str(new_eid),
            "tenant_id": str(cmd.tenant_id),
            "employer_id": str(cmd.employer_id),
            "plan_id": str(cmd.plan_id),
            "member_id": str(cmd.member_id),
            "relationship": cmd.relationship.value,
            "valid_from": cmd.valid_from.isoformat(),
            "valid_to": cmd.valid_to.isoformat(),
            "status": "active",
            "source_file_id": str(cmd.source_file_id) if cmd.source_file_id else None,
            "source_segment_ref": cmd.source_segment_ref,
        },
        headers={"topic": Topics.ENROLLMENT, "tenant_id": str(cmd.tenant_id)},
    )
    return new_eid


async def terminate_enrollment(
    s: AsyncSession, cmd: TerminateCommand, *, segment_key: str | None = None
) -> list[UUID]:
    repo = EnrollmentRepo(s)
    if segment_key and await repo.is_segment_processed(segment_key):
        raise DomainError(Codes.DUPLICATE_SEGMENT, "Segment already processed", http_status=200)
    closed = await repo.terminate_active_for_plan(
        cmd.tenant_id,
        cmd.member_id,
        cmd.plan_id,
        valid_to=cmd.valid_to,
        source_file_id=cmd.source_file_id,
        source_segment_ref=cmd.source_segment_ref,
    )
    if not closed:
        raise DomainError(
            Codes.MEMBER_NOT_FOUND,
            "No active enrollment found for that member+plan",
            http_status=404,
        )
    if segment_key:
        await repo.mark_segment_processed(segment_key)
    for eid in closed:
        await emit(
            s,
            aggregate="enrollment",
            aggregate_id=eid,
            event_type="EnrollmentTerminated",
            payload={
                "enrollment_id": str(eid),
                "tenant_id": str(cmd.tenant_id),
                "member_id": str(cmd.member_id),
                "plan_id": str(cmd.plan_id),
                "valid_to": cmd.valid_to.isoformat(),
            },
            headers={"topic": Topics.ENROLLMENT, "tenant_id": str(cmd.tenant_id)},
        )
    return closed


async def correct_enrollment(
    s: AsyncSession, cmd: CorrectionCommand, *, segment_key: str | None = None
) -> UUID:
    """Close the currently-in-force segment and open a corrected one.

    Retroactive DOB / plan / dates corrections all use this path. Bitemporal
    invariants: no existing row is mutated beyond `txn_to`.
    """
    repo = EnrollmentRepo(s)
    if segment_key and await repo.is_segment_processed(segment_key):
        raise DomainError(Codes.DUPLICATE_SEGMENT, "Segment already processed", http_status=200)
    timeline = await repo.load_timeline(cmd.tenant_id, cmd.member_id)
    active = [s for s in timeline.in_force() if s.plan_id == cmd.plan_id and s.status == Status.ACTIVE]
    for seg in active:
        await repo.close_segment(seg.id)
    new_eid = await repo.open_segment(
        tenant_id=cmd.tenant_id,
        employer_id=cmd.employer_id,
        subgroup_id=cmd.subgroup_id,
        plan_id=cmd.plan_id,
        member_id=cmd.member_id,
        relationship=cmd.relationship,
        status=Status.ACTIVE,
        valid_from=cmd.new_valid_from,
        valid_to=cmd.new_valid_to,
        source_file_id=cmd.source_file_id,
        source_segment_ref=cmd.source_segment_ref,
    )
    if segment_key:
        await repo.mark_segment_processed(segment_key)
    await emit(
        s,
        aggregate="enrollment",
        aggregate_id=new_eid,
        event_type="EnrollmentChanged",
        payload={
            "enrollment_id": str(new_eid),
            "tenant_id": str(cmd.tenant_id),
            "member_id": str(cmd.member_id),
            "plan_id": str(cmd.plan_id),
            "changes": {
                "valid_from": cmd.new_valid_from.isoformat(),
                "valid_to": cmd.new_valid_to.isoformat(),
            },
        },
        headers={"topic": Topics.ENROLLMENT, "tenant_id": str(cmd.tenant_id)},
    )
    return new_eid
