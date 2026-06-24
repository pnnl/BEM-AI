"""Internal tool interfaces and adapters."""

from __future__ import annotations

import abc
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)

ToolResultProvider = Literal[
    "anthropic", "bedrock", "google", "openai", "generic"
]


class RuntimeDeps(BaseModel):
    """Runtime dependencies passed to tool builders."""

    logger_name: str = "automa_ai.tools"


@dataclass(frozen=True)
class ToolResult:
    """Explicit tool result carrying structured data plus optional attachments."""

    data: dict[str, Any]
    attachments: list[Any] = field(default_factory=list)


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

    def as_langchain_tool(
        self, *, model_provider: ToolResultProvider = "generic"
    ):
        """Return a LangChain StructuredTool adapter."""
        from langchain_core.tools import StructuredTool

        async def _arun(**kwargs: Any) -> Any:
            return format_tool_result_content(
                await self.invoke(kwargs), model_provider=model_provider
            )

        return StructuredTool.from_function(
            name=self.name or self.type,
            description=self.description,
            args_schema=self.args_schema,
            coroutine=_arun,
        )


def infer_tool_result_provider(model: Any) -> ToolResultProvider:
    """Infer the tool-result renderer from a LangChain chat-model instance."""
    model_type = f"{type(model).__module__}.{type(model).__name__}".lower()
    if "langchain_aws" in model_type or "bedrock" in model_type:
        return "bedrock"
    if "langchain_anthropic" in model_type or "anthropic" in model_type:
        return "anthropic"
    if "langchain_google" in model_type or "generativeai" in model_type:
        return "google"
    if "langchain_openai" in model_type or "openai" in model_type:
        return "openai"
    return "generic"


def format_tool_result_content(
    result: Any, *, model_provider: ToolResultProvider = "generic"
) -> Any:
    """Render an explicit multimodal tool result for a model provider."""
    if not isinstance(result, ToolResult):
        return result
    if not result.attachments:
        return result.data

    image_blocks: list[dict[str, Any]] = []
    ignored_attachment_types: list[str] = []
    rendered_image_attachments = 0
    for attachment in result.attachments:
        if not isinstance(attachment, Mapping):
            ignored_attachment_types.append(type(attachment).__name__)
            continue
        mime_type = str(attachment.get("mime_type", ""))
        if not mime_type.startswith("image/"):
            ignored_attachment_types.append(mime_type or "unknown")
            continue
        if attachment.get("data"):
            if model_provider in {"anthropic", "bedrock"}:
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
            elif model_provider == "openai":
                image_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{attachment['data']}"
                        },
                    }
                )
            else:
                image_blocks.append(
                    {
                        "type": "image",
                        "base64": attachment["data"],
                        "mime_type": mime_type,
                    }
                )
            rendered_image_attachments += 1
        elif attachment.get("url"):
            if model_provider == "bedrock":
                raise ValueError(
                    "Bedrock tool-result images require inline base64 data; "
                    "remote image URLs are not supported."
                )
            if model_provider == "openai":
                image_blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": attachment["url"]},
                    }
                )
            elif model_provider == "anthropic":
                image_blocks.append(
                    {
                        "type": "image",
                        "source": {"type": "url", "url": attachment["url"]},
                    }
                )
            else:
                image_blocks.append(
                    {
                        "type": "image",
                        "url": attachment["url"],
                        "mime_type": mime_type,
                    }
                )
            rendered_image_attachments += 1
        else:
            ignored_attachment_types.append(mime_type)

    if ignored_attachment_types:
        logger.warning(
            "ToolResult ignored unsupported or malformed attachments: %s",
            ", ".join(ignored_attachment_types),
        )

    if model_provider == "openai":
        if rendered_image_attachments:
            logger.warning(
                "ToolResult included image attachments, but OpenAI tool "
                "responses are text-only, so the attachments were omitted."
            )
        return result.data

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


def content_to_safe_text(content: Any) -> str:
    """Project message content to text without retaining binary payloads."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [content_to_safe_text(item) for item in content]
        return "\n".join(part for part in parts if part)
    if not isinstance(content, Mapping):
        return str(content)

    block_type = str(content.get("type") or "")
    if block_type in {"text", "input_text", "output_text"}:
        return str(content.get("text") or "")

    mime_type = str(content.get("mime_type") or "")
    source = content.get("source")
    if not mime_type and isinstance(source, Mapping):
        mime_type = str(source.get("media_type") or source.get("mime_type") or "")

    if block_type in {
        "image",
        "image_url",
        "input_image",
        "audio",
        "video",
        "file",
        "media",
    } or (mime_type and ("data" in content or "base64" in content or "url" in content)):
        kind = mime_type or block_type or "attachment"
        return f"[{kind} attachment omitted from stream]"

    projected: dict[str, Any] = {}
    for key, value in content.items():
        if key == "base64":
            projected[key] = "[binary payload omitted]"
        elif key == "data" and str(content.get("type") or "") == "base64":
            projected[key] = "[binary payload omitted]"
        else:
            projected[key] = _project_safe_value(value)
    return json.dumps(projected, default=str, ensure_ascii=False)


def _project_safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        block_type = str(value.get("type") or "")
        return {
            key: (
                "[binary payload omitted]"
                if key == "base64" or (key == "data" and block_type == "base64")
                else _project_safe_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_safe_value(item) for item in value]
    return value
