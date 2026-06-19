"""Internal tool interfaces and adapters."""

from __future__ import annotations

import abc
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RuntimeDeps(BaseModel):
    """Runtime dependencies passed to tool builders."""

    logger_name: str = "automa_ai.tools"


@dataclass(frozen=True)
class ToolResult:
    """Explicit tool result carrying structured data plus optional attachments."""

    data: dict[str, Any]
    attachments: list[dict[str, Any]] = field(default_factory=list)


class BaseDefaultTool(abc.ABC):
    """Internal interface for default tools configured by users."""

    type: str
    name: str | None = None

    @property
    @abc.abstractmethod
    def args_schema(self) -> type[BaseModel]:
        """Pydantic schema for tool-call arguments."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM tool calling."""

    @abc.abstractmethod
    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any] | ToolResult:
        """Execute tool with structured payload."""

    def as_langchain_tool(self):
        """Return a LangChain StructuredTool adapter."""
        from langchain_core.tools import StructuredTool

        async def _arun(**kwargs: Any) -> Any:
            return _format_tool_result_content(await self.invoke(kwargs))

        return StructuredTool.from_function(
            name=self.name or self.type,
            description=self.description,
            args_schema=self.args_schema,
            coroutine=_arun,
        )


def _format_tool_result_content(result: Any) -> Any:
    """Convert explicit multimodal tool results into LangChain content blocks."""
    if not isinstance(result, ToolResult):
        return result
    if not result.attachments:
        return result.data

    image_blocks: list[dict[str, Any]] = []
    for attachment in result.attachments:
        if not isinstance(attachment, Mapping):
            continue
        mime_type = str(attachment.get("mime_type", ""))
        if not mime_type.startswith("image/"):
            continue
        if attachment.get("data"):
            # Anthropic content block format — langchain-aws's _snake_to_camel_keys
            # converts media_type → mediaType before passing to Bedrock Converse.
            image_blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": attachment["data"],
                    },
                }
            )
        elif attachment.get("url"):
            # OpenAI-style image_url block — langchain-aws converts to Bedrock format.
            image_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": attachment["url"]},
                }
            )

    if not image_blocks:
        logger.warning(
            "ToolResult included attachments, but no supported image attachments "
            "were converted to multimodal content blocks."
        )
        return result.data
    return [
        {
            "type": "text",
            "text": json.dumps(result.data, default=str, ensure_ascii=False),
        },
        *image_blocks,
    ]
