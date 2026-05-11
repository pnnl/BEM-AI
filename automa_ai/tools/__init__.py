"""Built-in default tools registry."""

from automa_ai.tools.registry import (
    DEFAULT_TOOL_REGISTRY,
    CUSTOM_TOOL_REGISTRY,
    build_langchain_tools,
)
from automa_ai.tools.decorators import tool
from automa_ai.tools.run_python import build_run_python_tool
from automa_ai.tools.web_search import build_web_search_tool
from automa_ai.tools.yaml_agent import build_yaml_agent_tool

import logging

for tool_type, builder in {
    "web_search": build_web_search_tool,
    "run_python": build_run_python_tool,
    "yaml_agent": build_yaml_agent_tool,
}.items():
    try:
        DEFAULT_TOOL_REGISTRY.register(tool_type, builder)
    except ValueError as exc:
        logging.getLogger(__name__).debug(
            "Ignoring ValueError while registering '%s' tool: %s",
            tool_type,
            exc,
        )

__all__ = [
    "DEFAULT_TOOL_REGISTRY",
    "CUSTOM_TOOL_REGISTRY",
    "build_langchain_tools",
    "tool",
]
