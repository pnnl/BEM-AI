from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class TurnRequest:
    """Structured request data passed through turn hooks and context providers.

    Hooks may return an updated request, but ``context_id`` is immutable for a
    turn because it identifies the checkpoint thread, blackboard, and session.
    """

    query: str
    context_id: str
    task_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_updates(self, **updates: Any) -> "TurnRequest":
        return replace(self, **updates)


@dataclass(frozen=True)
class TurnInputs:
    """Rendered LangGraph inputs plus context-collection diagnostics.

    ``degraded`` is true when the turn continued after one or more optional
    context providers failed. The missing provider names are included so hooks,
    telemetry, and eval harnesses can distinguish a full-context answer from an
    answer generated without every requested context source.
    """

    turn: TurnRequest
    inputs: dict[str, Any]
    degraded: bool = False
    missing_providers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TurnResult:
    """Stable result contract passed to after-turn hooks.

    ``content`` and ``artifact_content`` are the path-independent fields hook
    authors should prefer. ``raw_response`` is populated by invoke calls for
    callers that need the original LangGraph state; ``final_output`` is
    populated by stream calls with the final user-facing A2A event.
    ``degraded`` mirrors ``TurnInputs.degraded`` for downstream observability.
    """

    mode: str
    content: str
    artifact_content: str = ""
    raw_response: Any | None = None
    final_output: dict[str, Any] | None = None
    status: str = "completed"
    degraded: bool = False
    missing_providers: list[str] = field(default_factory=list)
