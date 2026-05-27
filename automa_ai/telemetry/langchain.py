"""LangChain tool adapters for telemetry."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from automa_ai.telemetry.facade import Telemetry


def wrap_langchain_tool(
    tool: Any,
    telemetry: Telemetry,
    *,
    source_type: str,
) -> Any:
    """Wrap a LangChain tool with a telemetry span.

    LangGraph only needs a normal LangChain tool object, so this adapter keeps
    the original name/schema/description and intercepts the coroutine path to
    record input/output events around the actual `ainvoke`.
    """

    if not telemetry.enabled:
        return tool
    if getattr(tool, "_automa_telemetry_wrapped", False):
        return tool

    tool_name = getattr(tool, "name", "<unknown>")
    description = getattr(tool, "description", "") or ""
    args_schema = getattr(tool, "args_schema", None)

    async def _arun(config: RunnableConfig, **kwargs: Any) -> Any:
        """StructuredTool coroutine preserving the original tool call contract."""
        async with telemetry.span(
            "tool.call",
            kind="client",
            attributes={
                "tool.name": tool_name,
                "tool.source": source_type,
                "tool.arguments": kwargs,
            },
        ):
            telemetry.event(
                "tool.input",
                attributes={
                    "tool.name": tool_name,
                    "tool.source": source_type,
                    "tool.arguments": kwargs,
                },
            )
            result = await tool.ainvoke(kwargs, config=config)
            telemetry.event(
                "tool.output",
                attributes={
                    "tool.name": tool_name,
                    "tool.source": source_type,
                    "tool.result": result,
                },
            )
            return result

    wrapped = StructuredTool.from_function(
        name=tool_name,
        description=description,
        args_schema=args_schema,
        coroutine=_arun,
        return_direct=getattr(tool, "return_direct", False),
        response_format=getattr(tool, "response_format", "content"),
        handle_tool_error=getattr(tool, "handle_tool_error", False),
        handle_validation_error=getattr(tool, "handle_validation_error", False),
        verbose=getattr(tool, "verbose", False),
        callbacks=getattr(tool, "callbacks", None),
        tags=getattr(tool, "tags", None),
        metadata=getattr(tool, "metadata", None),
    )
    setattr(wrapped, "_automa_telemetry_wrapped", True)
    setattr(wrapped, "_automa_telemetry_source", source_type)
    return wrapped
