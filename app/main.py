from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from eligibility_common.app_factory import create_app
from eligibility_common.db import engine, session_scope
from eligibility_common.idempotency import IDEMPOTENCY_DDL_STATEMENTS
from eligibility_common.outbox import OUTBOX_DDL_STATEMENTS
from fastapi import FastAPI
from sqlalchemy import text

from app.interfaces.api import router
from app.settings import settings


_ATLAS_DDL = [
    """
    CREATE TABLE IF NOT EXISTS enrollments (
      id UUID PRIMARY KEY,
      tenant_id UUID NOT NULL,
      employer_id UUID NOT NULL,
      subgroup_id UUID,
      plan_id UUID NOT NULL,
      member_id UUID NOT NULL,
      relationship TEXT NOT NULL,
      status TEXT NOT NULL,
      valid_from DATE NOT NULL,
      valid_to DATE NOT NULL,
      txn_from TIMESTAMPTZ NOT NULL DEFAULT now(),
      txn_to TIMESTAMPTZ NOT NULL,
      source_file_id UUID,
      source_segment_ref TEXT,
      version BIGINT NOT NULL DEFAULT 1,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS enr_member_inforce ON enrollments (tenant_id, member_id, valid_from)",
    "CREATE INDEX IF NOT EXISTS enr_employer_active ON enrollments (tenant_id, employer_id, status, valid_from)",
    """
    CREATE TABLE IF NOT EXISTS processed_segments (
      segment_key TEXT PRIMARY KEY,
      processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sagas (
      id UUID PRIMARY KEY,
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      state JSONB NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]


@asynccontextmanager
async def lifespan(_app: FastAPI):  # type: ignore[no-untyped-def]
    async with engine().begin() as conn:
        for stmt in OUTBOX_DDL_STATEMENTS + IDEMPOTENCY_DDL_STATEMENTS + _ATLAS_DDL:
            await conn.execute(text(stmt))
    yield


async def _ping_db() -> None:
    async with session_scope() as s:
        await s.execute(text("SELECT 1"))


app = create_app(
    service_name=settings.service_name,
    lifespan=lifespan,
    readiness={"db": _ping_db},
)
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
