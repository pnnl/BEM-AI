from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class LearningEvent:
    event_type: str
    source: str
    payload: dict[str, Any]
    workflow_id: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "source": self.source,
            "workflow_id": self.workflow_id,
            "created_at": self.created_at,
            "payload": self.payload,
        }

