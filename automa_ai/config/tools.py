"""Configuration models for first-class default tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """Declarative tool configuration entry."""

    type: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ToolsConfig(BaseModel):
    """Container for declarative tool configuration."""

    tools: list[ToolSpec] = Field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolsConfig":
        return cls.model_validate(data)
