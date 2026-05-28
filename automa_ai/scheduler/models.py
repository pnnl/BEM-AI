"""Data models for scheduled prompt loops."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class LoopTaskStatus(StrEnum):
    """Lifecycle states for a scheduled loop task."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(slots=True)
class LoopTask:
    """One recurring prompt within a scheduler session."""

    id: str
    prompt: str
    interval: timedelta
    context_id: str
    created_at: datetime
    next_run_at: datetime
    expires_at: datetime
    status: LoopTaskStatus = LoopTaskStatus.ACTIVE
    run_count: int = 0
    last_run_at: datetime | None = None
    last_error: str | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the task should still be considered runnable."""
        return self.status == LoopTaskStatus.ACTIVE
