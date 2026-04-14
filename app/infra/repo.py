"""Repository — the only place that touches the DB for Enrollment aggregate.

Bitemporal writes are expressed as a pair of UPDATE (close) + INSERT (open).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enrollment import (
    INFINITY_DATE,
    INFINITY_TS,
    EnrollmentSegment,
    Relationship,
    Status,
    Timeline,
    new_id,
    now_utc,
)


class EnrollmentRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def load_timeline(self, tenant_id: UUID, member_id: UUID) -> Timeline:
        rows = (
            await self.s.execute(
                text(
                    """
                    SELECT id, tenant_id, employer_id, subgroup_id, plan_id, member_id,
                           relationship, status, valid_from, valid_to, txn_from, txn_to,
                           source_file_id, source_segment_ref, version
                    FROM enrollments
                    WHERE tenant_id = :t AND member_id = :m
                    ORDER BY valid_from DESC, txn_from DESC
                    """
                ),
                {"t": str(tenant_id), "m": str(member_id)},
            )
        ).all()
        segs = [
            EnrollmentSegment(
                id=r.id,
                tenant_id=r.tenant_id,
                employer_id=r.employer_id,
                subgroup_id=r.subgroup_id,
                plan_id=r.plan_id,
                member_id=r.member_id,
                relationship=Relationship(r.relationship),
                status=Status(r.status),
                valid_from=r.valid_from,
                valid_to=r.valid_to,
                txn_from=r.txn_from,
                txn_to=r.txn_to,
                source_file_id=r.source_file_id,
                source_segment_ref=r.source_segment_ref,
                version=r.version,
            )
            for r in rows
        ]
        return Timeline(segments=segs)

    async def is_segment_processed(self, segment_key: str) -> bool:
        if not segment_key:
            return False
        row = (
            await self.s.execute(
                text("SELECT 1 FROM processed_segments WHERE segment_key = :k"),
                {"k": segment_key},
            )
        ).first()
        return row is not None

    async def mark_segment_processed(self, segment_key: str) -> None:
        await self.s.execute(
            text(
                """
                INSERT INTO processed_segments (segment_key) VALUES (:k)
                ON CONFLICT (segment_key) DO NOTHING
                """
            ),
            {"k": segment_key},
        )

    async def open_segment(
        self,
        *,
        tenant_id: UUID,
        employer_id: UUID,
        subgroup_id: UUID | None,
        plan_id: UUID,
        member_id: UUID,
        relationship: Relationship,
        status: Status,
        valid_from: date,
        valid_to: date = INFINITY_DATE,
        source_file_id: UUID | None = None,
        source_segment_ref: str | None = None,
    ) -> UUID:
        new = new_id()
        await self.s.execute(
            text(
                """
                INSERT INTO enrollments
                  (id, tenant_id, employer_id, subgroup_id, plan_id, member_id,
                   relationship, status, valid_from, valid_to, txn_from, txn_to,
                   source_file_id, source_segment_ref, version)
                VALUES
                  (:id, :t, :e, :sg, :p, :m,
                   :rel, :st, :vf, :vt, :tf, :tt,
                   :sf, :ssr, 1)
                """
            ),
            {
                "id": str(new),
                "t": str(tenant_id),
                "e": str(employer_id),
                "sg": str(subgroup_id) if subgroup_id else None,
                "p": str(plan_id),
                "m": str(member_id),
                "rel": relationship.value,
                "st": status.value,
                "vf": valid_from,
                "vt": valid_to,
                "tf": now_utc(),
                "tt": INFINITY_TS,
                "sf": str(source_file_id) if source_file_id else None,
                "ssr": source_segment_ref,
            },
        )
        return new

    async def close_segment(self, segment_id: UUID, *, as_of: datetime | None = None) -> None:
        """Close an in-force row. `as_of` defaults to now."""
        ts = as_of or now_utc()
        await self.s.execute(
            text(
                """
                UPDATE enrollments
                SET txn_to = :tt
                WHERE id = :id AND txn_to >= :inf
                """
            ),
            {"id": str(segment_id), "tt": ts, "inf": INFINITY_TS},
        )

    async def terminate_active_for_plan(
        self,
        tenant_id: UUID,
        member_id: UUID,
        plan_id: UUID,
        *,
        valid_to: date,
        source_file_id: UUID | None = None,
        source_segment_ref: str | None = None,
    ) -> list[UUID]:
        """Close any in-force active segments and open a TERMED row ending at `valid_to`."""
        timeline = await self.load_timeline(tenant_id, member_id)
        closed: list[UUID] = []
        for seg in timeline.in_force():
            if seg.plan_id != plan_id or seg.status != Status.ACTIVE:
                continue
            # business check: we only shorten segments into the past
            if seg.valid_from > valid_to:
                continue
            await self.close_segment(seg.id)
            await self.open_segment(
                tenant_id=seg.tenant_id,
                employer_id=seg.employer_id,
                subgroup_id=seg.subgroup_id,
                plan_id=seg.plan_id,
                member_id=seg.member_id,
                relationship=seg.relationship,
                status=Status.TERMED,
                valid_from=seg.valid_from,
                valid_to=valid_to,
                source_file_id=source_file_id,
                source_segment_ref=source_segment_ref,
            )
            closed.append(seg.id)
        return closed
