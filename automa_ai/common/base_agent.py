import abc
from abc import ABC
from typing import Any, AsyncIterable

from pydantic import BaseModel, Field


class BaseAgent(BaseModel, ABC):
    """Base class for agents."""

    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "allow",
    }

    agent_name: str = Field(description="The name of the agent.")

    description: str = Field(description="A brief description of the agent's purpose.")

    content_types: list[str] = Field(description="Supported content types.")

    @abc.abstractmethod
    async def invoke(self, query, context_id, task_id, user_id: str | None = None, metadata: dict[str, Any] | None = None):
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def stream(self, query, context_id, task_id, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> AsyncIterable[dict[str, Any]]:
        raise NotImplementedError()