"""Saga state machine for multi-step workflows (REPLACE_FILE, PLAN_CHANGE_FAMILY).

Each step declares execute+compensate. Orchestrator persists state in `sagas`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SagaStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    COMPENSATED = "COMPENSATED"


@dataclass
class SagaStep:
    name: str
    execute: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    compensate: Callable[[dict[str, Any]], Awaitable[None]] | None = None


@dataclass
class SagaDef:
    kind: str
    steps: list[SagaStep] = field(default_factory=list)
