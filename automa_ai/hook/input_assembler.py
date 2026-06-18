from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from automa_ai.hook.context import ContextBlock
from automa_ai.hook.turn import TurnRequest


class InputAssembler:
    """Builds LangGraph inputs from a turn and collected context blocks."""

    def _build_user_content(self, turn: TurnRequest) -> str | list[dict[str, Any]]:
        """Build user message content, supporting multimodal image attachments."""
        if not turn.attachments:
            return turn.query

        content_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": turn.query}
        ]
        for attachment in turn.attachments:
            mime_type = attachment.get("mime_type", "")
            if mime_type.startswith("image/") and attachment.get("data"):
                content_blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": attachment["data"],
                        },
                    }
                )
        return content_blocks

    def build(
        self,
        *,
        turn: TurnRequest,
        context_blocks: Iterable[ContextBlock],
    ) -> dict[str, Any]:
        """Render context blocks and the user query into LangGraph inputs."""
        messages: list[dict[str, Any]] = []
        system_context = "\n\n".join(
            block.content for block in context_blocks if block.role == "system"
        )
        if system_context.strip():
            messages.append({"role": "system", "content": system_context})
        messages.append({"role": "user", "content": self._build_user_content(turn)})
        return {"messages": messages}
