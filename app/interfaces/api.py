from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from eligibility_common.db import session_scope
from eligibility_common.errors import Codes, ValidationError
from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from app.application.commands import (
    add_enrollment,
    correct_enrollment,
    terminate_enrollment,
)
from app.domain.enrollment import (
    INFINITY_DATE,
    AddCommand,
    CorrectionCommand,
    Relationship,
    Status,
    TerminateCommand,
)
from app.infra.repo import EnrollmentRepo

router = APIRouter(prefix="", tags=["atlas"])


class CommandIn(BaseModel):
    command_type: Literal["ADD", "TERMINATE", "CORRECTION"]
    tenant_id: UUID
    employer_id: UUID | None = None
    subgroup_id: UUID | None = None
    plan_id: UUID
    member_id: UUID
    relationship: Relationship = Relationship.SUBSCRIBER
    valid_from: date | None = None
    valid_to: date | None = None
    new_valid_from: date | None = None
    new_valid_to: date | None = None
    source_file_id: UUID | None = None
    source_segment_ref: str | None = Field(None, description="ISA13:GS06:ST02:INS_pos")


class CommandOut(BaseModel):
    enrollment_ids: list[UUID]


@router.post("/commands", response_model=CommandOut, status_code=200)
async def run_command(body: CommandIn, request: Request) -> CommandOut:
    seg_key = body.source_segment_ref or None
    async with session_scope(tenant_id=str(body.tenant_id)) as s:
        if body.command_type == "ADD":
            if not body.employer_id or not body.valid_from:
                raise ValidationError(Codes.INVALID_834, "ADD requires employer_id + valid_from")
            eid = await add_enrollment(
                s,
                AddCommand(
                    tenant_id=body.tenant_id,
                    employer_id=body.employer_id,
                    subgroup_id=body.subgroup_id,
                    plan_id=body.plan_id,
                    member_id=body.member_id,
                    relationship=body.relationship,
                    valid_from=body.valid_from,
                    valid_to=body.valid_to or INFINITY_DATE,
                    source_file_id=body.source_file_id,
                    source_segment_ref=body.source_segment_ref,
                ),
                segment_key=seg_key,
            )
            return CommandOut(enrollment_ids=[eid])
        if body.command_type == "TERMINATE":
            if not body.valid_to:
                raise ValidationError(Codes.INVALID_834, "TERMINATE requires valid_to")
            closed = await terminate_enrollment(
                s,
                TerminateCommand(
                    tenant_id=body.tenant_id,
                    member_id=body.member_id,
                    plan_id=body.plan_id,
                    valid_to=body.valid_to,
                    source_file_id=body.source_file_id,
                    source_segment_ref=body.source_segment_ref,
                ),
                segment_key=seg_key,
            )
            return CommandOut(enrollment_ids=closed)
        if body.command_type == "CORRECTION":
            if not (body.new_valid_from and body.new_valid_to and body.employer_id):
                raise ValidationError(
                    Codes.INVALID_834, "CORRECTION requires new_valid_from+new_valid_to+employer_id"
                )
            eid = await correct_enrollment(
                s,
                CorrectionCommand(
                    tenant_id=body.tenant_id,
                    member_id=body.member_id,
                    plan_id=body.plan_id,
                    new_valid_from=body.new_valid_from,
                    new_valid_to=body.new_valid_to,
                    employer_id=body.employer_id,
                    subgroup_id=body.subgroup_id,
                    relationship=body.relationship,
                    source_file_id=body.source_file_id,
                    source_segment_ref=body.source_segment_ref,
                ),
                segment_key=seg_key,
            )
            return CommandOut(enrollment_ids=[eid])
        raise ValidationError(Codes.INVALID_834, f"Unknown command_type={body.command_type}")


class TimelineOut(BaseModel):
    segments: list[dict]


@router.get("/members/{member_id}/timeline", response_model=TimelineOut)
async def timeline(
    member_id: UUID,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-Id"),
) -> TimelineOut:
    async with session_scope(tenant_id=str(x_tenant_id)) as s:
        repo = EnrollmentRepo(s)
        tl = await repo.load_timeline(x_tenant_id, member_id)
        return TimelineOut(
            segments=[
                {
                    "id": str(seg.id),
                    "plan_id": str(seg.plan_id),
                    "employer_id": str(seg.employer_id),
                    "relationship": seg.relationship.value,
                    "status": seg.status.value,
                    "valid_from": seg.valid_from.isoformat(),
                    "valid_to": seg.valid_to.isoformat(),
                    "txn_from": seg.txn_from.isoformat(),
                    "txn_to": seg.txn_to.isoformat(),
                    "is_in_force": seg.is_in_force,
                    "source_file_id": str(seg.source_file_id) if seg.source_file_id else None,
                    "source_segment_ref": seg.source_segment_ref,
                }
                for seg in tl.segments
            ]
        )
