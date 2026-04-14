from datetime import date, datetime, timezone
from uuid import uuid4

from app.domain.enrollment import (
    INFINITY_DATE,
    INFINITY_TS,
    EnrollmentSegment,
    Relationship,
    Status,
    Timeline,
)


def make_seg(**overrides):
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "employer_id": uuid4(),
        "subgroup_id": None,
        "plan_id": uuid4(),
        "member_id": uuid4(),
        "relationship": Relationship.SUBSCRIBER,
        "status": Status.ACTIVE,
        "valid_from": date(2026, 1, 1),
        "valid_to": INFINITY_DATE,
        "txn_from": datetime.now(timezone.utc),
        "txn_to": INFINITY_TS,
        "source_file_id": None,
        "source_segment_ref": None,
    }
    base.update(overrides)
    return EnrollmentSegment(**base)


def test_is_in_force_true_when_txn_to_infinity() -> None:
    seg = make_seg()
    assert seg.is_in_force is True


def test_is_in_force_false_when_closed() -> None:
    seg = make_seg(txn_to=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert seg.is_in_force is False


def test_overlaps_simple() -> None:
    seg = make_seg(valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
    assert seg.overlaps(date(2026, 4, 1), date(2026, 7, 1)) is True
    assert seg.overlaps(date(2026, 7, 1), date(2026, 12, 31)) is False


def test_timeline_overlaps_filters_by_plan_and_active() -> None:
    plan = uuid4()
    other_plan = uuid4()
    tl = Timeline(
        segments=[
            make_seg(plan_id=plan, valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30)),
            make_seg(
                plan_id=plan,
                status=Status.TERMED,
                valid_from=date(2025, 1, 1),
                valid_to=date(2025, 12, 31),
            ),
            make_seg(plan_id=other_plan, valid_from=date(2026, 1, 1), valid_to=INFINITY_DATE),
        ]
    )
    overlaps = tl.overlaps_with(date(2026, 4, 1), date(2026, 7, 1), plan)
    assert len(overlaps) == 1  # only active on this plan


def test_in_force_excludes_closed_rows() -> None:
    live = make_seg()
    history = make_seg(txn_to=datetime(2026, 3, 1, tzinfo=timezone.utc))
    tl = Timeline(segments=[live, history])
    assert tl.in_force() == [live]
