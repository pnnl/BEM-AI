from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from automa_ai.hook.context import ContextBlock
from automa_ai.hook.turn import TurnRequest


class InputAssembler:
    """Builds LangGraph inputs from a turn and collected context blocks."""

    def build(
        self,
        *,
        turn: TurnRequest,
        context_blocks: Iterable[ContextBlock],
    ) -> dict[str, Any]:
        """Render context blocks and the user query into LangGraph inputs."""
        messages: list[dict[str, str]] = []
        system_context = "\n\n".join(
            block.content for block in context_blocks if block.role == "system"
        )
        if system_context.strip():
            messages.append({"role": "system", "content": system_context})
        messages.append({"role": "user", "content": turn.query})
        return {"messages": messages}
