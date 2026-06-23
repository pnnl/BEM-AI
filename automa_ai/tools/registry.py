"""Extensible registry for default built-in tools."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from typing import Any

from automa_ai.config.tools import ToolSpec
from automa_ai.tools.base import (
    BaseDefaultTool,
    RuntimeDeps,
    ToolResultProvider,
)

ToolBuilder = Callable[[dict[str, Any], RuntimeDeps], BaseDefaultTool]


class ToolNotFoundError(ValueError):
    pass

class ToolRegistry:
    """Maps tool type to a builder implementation."""

    def __init__(self):
        self._builders: dict[str, ToolBuilder] = {}

    def register(self, tool_type: str, builder: ToolBuilder) -> None:
        if (
            tool_type in self._builders 
            or tool_type in DEFAULT_TOOL_REGISTRY._builders 
            or tool_type in CUSTOM_TOOL_REGISTRY._builders
        ):
            raise ValueError(f"Tool type '{tool_type}' is already registered.")
        
        self._builders[tool_type] = builder

    def build(self, spec: ToolSpec, runtime_deps: RuntimeDeps | None = None) -> BaseDefaultTool:
        tool_type = spec.type

        # Use default runtime deps if not provided
        if runtime_deps is None:
            runtime_deps = RuntimeDeps()

        # Auto-import if type contains dots (e.g., "mydir.tools.my_tool")
        if tool_type not in self._builders and "." in tool_type:
            self._try_auto_import(tool_type)

        if tool_type not in self._builders:
            raise ToolNotFoundError(
                f"Unknown tool type '{tool_type}'. "
                f"Known tools: {sorted(self._builders)}"
            )

        return self._builders[tool_type](spec.config, runtime_deps)

    def _try_auto_import(self, tool_type: str) -> None:
        """Try importing module from dotted tool type.
        """
        parts = tool_type.rsplit(".", 1)
        if len(parts) != 2:
            return
        
        module_path, _ = parts
        
        importlib.import_module(module_path)


DEFAULT_TOOL_REGISTRY = ToolRegistry()
CUSTOM_TOOL_REGISTRY = ToolRegistry()


def build_langchain_tools(
    tool_specs: list[ToolSpec] | None,
    logger: logging.Logger | None = None,
    *,
    model_provider: ToolResultProvider = "generic",
) -> list[Any]:
    """Build configured tools and adapt them for LangChain.

    Checks both DEFAULT_TOOL_REGISTRY (built-in tools) and CUSTOM_TOOL_REGISTRY
    (user-defined @tool decorated functions). For custom tools, supports auto-import
    via dotted paths (e.g., "mydir.tools.my_tool").
    """
    if not tool_specs:
        return []

    runtime_deps = RuntimeDeps(
        logger_name=(logger.name if logger else "automa_ai.tools")
    )
    built: list[Any] = []
    for spec in tool_specs:
        # Try DEFAULT_TOOL_REGISTRY first (built-ins like web_search)
        try:
            tool = DEFAULT_TOOL_REGISTRY.build(spec, runtime_deps)
        except ToolNotFoundError:
            # Fall back to CUSTOM_TOOL_REGISTRY
            tool = CUSTOM_TOOL_REGISTRY.build(spec, runtime_deps)

        built.append(tool.as_langchain_tool(model_provider=model_provider))
    return built
