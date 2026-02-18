"""Internal tool interfaces and adapters."""

from __future__ import annotations

import abc
from typing import Any

from pydantic import BaseModel


class RuntimeDeps(BaseModel):
    """Runtime dependencies passed to tool builders."""

    logger_name: str = "automa_ai.tools"


class BaseDefaultTool(abc.ABC):
    """Internal interface for default tools configured by users."""

    type: str

    @property
    @abc.abstractmethod
    def args_schema(self) -> type[BaseModel]:
        """Pydantic schema for tool-call arguments."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable description for LLM tool calling."""

    @abc.abstractmethod
    async def invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute tool with structured payload."""

    def as_langchain_tool(self):
        """Return a LangChain StructuredTool adapter."""
        from langchain_core.tools import StructuredTool

        async def _arun(**kwargs: Any) -> dict[str, Any]:
            return await self.invoke(kwargs)

        return StructuredTool.from_function(
            name=self.type,
            description=self.description,
            args_schema=self.args_schema,
            coroutine=_arun,
        )
