from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class TurnRequest:
    """Structured request data passed through turn hooks and context providers."""

    query: str
    context_id: str
    task_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "TurnRequest":
        return replace(self, **updates)


@dataclass(frozen=True)
class TurnInputs:
    """Rendered LangGraph inputs plus the final turn request that produced them."""

    turn: TurnRequest
    inputs: dict[str, Any]
