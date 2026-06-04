from __future__ import annotations

import logging
import inspect
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from automa_ai.hook.turn import TurnRequest
from automa_ai.memory.memory_types import MemoryType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextBlock:
    """A named context section that can be assembled into model inputs."""

    name: str
    content: str
    priority: int = 0
    role: str = "system"
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ContextCollection:
    """Context blocks plus diagnostics for providers that failed open."""

    blocks: list[ContextBlock]
    missing_providers: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """Return true when at least one provider failed during collection."""
        return bool(self.missing_providers)


class ContextProvider(Protocol):
    async def collect(self, turn: TurnRequest) -> ContextBlock | list[ContextBlock] | None:
        ...


ContextProviderErrorHandler = Callable[
    [ContextProvider, Exception, TurnRequest],
    Awaitable[None] | None,
]


class ContextPipeline:
    """Collects context blocks from configured providers."""

    def __init__(self, providers: Iterable[ContextProvider] | None = None) -> None:
        self._providers = list(providers or [])

    @classmethod
    def empty(cls) -> "ContextPipeline":
        """Return a pipeline with no context providers."""
        return cls()

    async def collect(
        self,
        turn: TurnRequest,
        *,
        on_provider_error: ContextProviderErrorHandler | None = None,
    ) -> ContextCollection:
        """Collect context blocks and record failed optional providers.

        Provider failures are intentionally degraded here: one broken retrieval
        or memory source should not abort the whole turn when callers have
        chosen fail-open context semantics.
        """
        collected: list[tuple[int, ContextBlock]] = []
        missing_providers: list[str] = []
        for index, provider in enumerate(self._providers):
            try:
                result = await provider.collect(turn)
            except Exception as exc:
                provider_name = provider.__class__.__name__
                missing_providers.append(provider_name)
                logger.warning(
                    "Context provider %s failed for session %s; continuing "
                    "without that context block.",
                    provider_name,
                    turn.context_id,
                    exc_info=True,
                )
                if on_provider_error is not None:
                    try:
                        # Reporting degraded context is best effort; the
                        # original provider failure should not become fatal
                        # because telemetry or a callback failed too.
                        maybe_awaitable = on_provider_error(provider, exc, turn)
                        if inspect.isawaitable(maybe_awaitable):
                            await maybe_awaitable
                    except Exception:
                        logger.warning(
                            "Context provider error handler failed for %s.",
                            provider_name,
                            exc_info=True,
                        )
                continue
            if result is None:
                continue
            blocks = result if isinstance(result, list) else [result]
            for block in blocks:
                if block.content.strip():
                    collected.append((index, block))
        collected.sort(key=lambda item: (-item[1].priority, item[0]))
        return ContextCollection(
            blocks=[block for _, block in collected],
            missing_providers=missing_providers,
        )


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
        """Retrieve knowledge-base context for the current query."""
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
        """Retrieve prior conversation memory for the current turn."""
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
