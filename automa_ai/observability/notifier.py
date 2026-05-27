from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AgentEvent:
    event_type: str
    source: str
    message: str
    session_id: str | None = None
    task_id: str | None = None
    target: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EventNotifier(ABC):
    @abstractmethod
    async def emit(self, event: AgentEvent) -> None:
        """Best-effort event publication."""


class NoOpEventNotifier(EventNotifier):
    async def emit(self, event: AgentEvent) -> None:
        return None
