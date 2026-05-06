"""Configuration models for first-class default tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Declarative tool configuration entry.

    ``type`` is the lookup key consumed by the tool registry. Built-in tools use
    short names such as ``web_search``, ``run_python``, or ``yaml_agent``.
    Custom ``@tool`` functions should use their fully qualified dotted function
    path, for example ``my_package.tools.search_codes``; the registry imports
    the module from that path before building the tool.
    """

    type: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolsConfig(BaseModel):
    """Container for declarative tool configuration passed to ``AgentFactory``."""

    tools: list[ToolSpec] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolsConfig":
        return cls.model_validate(data)
