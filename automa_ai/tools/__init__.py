"""Built-in default tools registry."""

from automa_ai.tools.registry import DEFAULT_TOOL_REGISTRY, build_langchain_tools
from automa_ai.tools.run_python import build_run_python_tool
from automa_ai.tools.web_search import build_web_search_tool

import logging

try:
    DEFAULT_TOOL_REGISTRY.register("web_search", build_web_search_tool)
except ValueError as exc:
    logging.getLogger(__name__).debug(
        "Ignoring ValueError while registering 'web_search' tool: %s",
        exc,
    )

try:
    DEFAULT_TOOL_REGISTRY.register("run_python", build_run_python_tool)
except ValueError as exc:
    logging.getLogger(__name__).debug(
        "Ignoring ValueError while registering 'run_python' tool: %s",
        exc,
    )

__all__ = ["DEFAULT_TOOL_REGISTRY", "build_langchain_tools"]
