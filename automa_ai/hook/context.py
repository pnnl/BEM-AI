from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from automa_ai.hook.turn import TurnRequest
from automa_ai.memory.memory_types import MemoryType


@dataclass(frozen=True)
class ContextBlock:
    """A named context section that can be assembled into model inputs."""

    name: str
    content: str
    priority: int = 0
    role: str = "system"
    metadata: dict[str, Any] | None = None


class ContextProvider(Protocol):
    async def collect(self, turn: TurnRequest) -> ContextBlock | list[ContextBlock] | None:
        ...


class ContextPipeline:
    """Collects context blocks from configured providers."""

    def __init__(self, providers: Iterable[ContextProvider] | None = None) -> None:
        self._providers = list(providers or [])

    @classmethod
    def empty(cls) -> "ContextPipeline":
        return cls()

    async def collect(self, turn: TurnRequest) -> list[ContextBlock]:
        collected: list[tuple[int, ContextBlock]] = []
        for index, provider in enumerate(self._providers):
            result = await provider.collect(turn)
            if result is None:
                continue
            blocks = result if isinstance(result, list) else [result]
            for block in blocks:
                if block.content.strip():
                    collected.append((index, block))
        collected.sort(key=lambda item: (-item[1].priority, item[0]))
        return [block for _, block in collected]


class RetrieverContextProvider:
    """Adds retrieval context using the configured retriever."""

    def __init__(
        self,
        retriever: Any,
        *,
        priority: int = 100,
        logger: logging.Logger | None = None,
        debug: bool = False,
    ) -> None:
        self.retriever = retriever
        self.priority = priority
        self.logger = logger
        self.debug = debug

    async def collect(self, turn: TurnRequest) -> ContextBlock | None:
        context = await self.retriever.asimilarity_search(turn.query)
        if not context:
            return None

        content = (
            "You are given the following context from the knowledge base:\n"
            f"{context}"
        )
        if self.debug:
            if self.logger:
                self.logger.info("Retrieved query context: %s", content)
            print(content)
        return ContextBlock(
            name="retrieval",
            content=content,
            priority=self.priority,
        )


class MemoryContextProvider:
    """Adds prior-conversation memory context using the configured memory manager."""

    def __init__(
        self,
        memory_manager: Any,
        *,
        priority: int = 90,
        logger: logging.Logger | None = None,
        debug: bool = False,
    ) -> None:
        self.memory_manager = memory_manager
        self.priority = priority
        self.logger = logger
        self.debug = debug

    async def collect(self, turn: TurnRequest) -> ContextBlock | None:
        memory_list = await self.memory_manager.retrieve_memories(
            turn.query,
            session_id=turn.context_id,
            task_id=turn.task_id,
            user_id=turn.user_id,
            metadata=turn.metadata,
            memory_types=[MemoryType.SHORT_TERM, MemoryType.LONG_TERM],
            include_short_term=True,
            include_long_term=True,
        )
        if not memory_list:
            return None

        formatted = "\n".join(f"{m.timestamp}: {m.content}" for m in memory_list)
        content = (
            "You are also given the following context from past conversations "
            f"with the user:\n{formatted}"
        )
        if self.debug and self.logger:
            self.logger.info("Retrieved memory context: %s", content)
        return ContextBlock(
            name="memory",
            content=content,
            priority=self.priority,
        )
