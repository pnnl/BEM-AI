"""Extensible registry for default built-in tools."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from automa_ai.config.tools import ToolSpec
from automa_ai.tools.base import BaseDefaultTool, RuntimeDeps

ToolBuilder = Callable[[dict[str, Any], RuntimeDeps], BaseDefaultTool]


class ToolRegistry:
    """Maps tool type to a builder implementation."""

    def __init__(self):
        self._builders: dict[str, ToolBuilder] = {}

    def register(self, tool_type: str, builder: ToolBuilder) -> None:
        if tool_type in self._builders:
            raise ValueError(f"Tool type '{tool_type}' is already registered.")
        self._builders[tool_type] = builder

    def build(self, spec: ToolSpec, runtime_deps: RuntimeDeps) -> BaseDefaultTool:
        if spec.type not in self._builders:
            raise ValueError(f"Unknown tool type '{spec.type}'.")
        return self._builders[spec.type](spec.config, runtime_deps)


DEFAULT_TOOL_REGISTRY = ToolRegistry()


def build_langchain_tools(
    tool_specs: list[ToolSpec] | None, logger: logging.Logger | None = None
) -> list[Any]:
    """Build configured tools and adapt them for LangChain."""
    if not tool_specs:
        return []
    runtime_deps = RuntimeDeps(
        logger_name=(logger.name if logger else "automa_ai.tools")
    )
    built: list[Any] = []
    for spec in tool_specs:
        built.append(
            DEFAULT_TOOL_REGISTRY.build(spec, runtime_deps).as_langchain_tool()
        )
    return built
