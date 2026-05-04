"""Memory module for managing conversation history and context retrieval"""

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from automa_ai.memory.memory_stores import BaseMemoryStore, MemoryStoreRegistry
from automa_ai.memory.memory_types import MemoryType, MemoryEntry

DEFAULT_SHORT_TERM_LIMIT = 10
DEFAULT_LONG_TERM_STRATEGY = "summarize"
DEFAULT_SHORT_TERM_MAX = 30
DEFAULT_LONG_TERM_TYPES: tuple[MemoryType, ...] = (
    MemoryType.LONG_TERM,
    MemoryType.EPISODIC,
    MemoryType.SEMANTIC,
)

from dataclasses import dataclass
from typing import Optional
from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)


@dataclass
class MemoryWriteEvent:
    # data class define memory writing event
    message: BaseMessage
    session_id: str
    task_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class DefaultMemoryManager:
    """
    Memory Manager Configuration
    short_term_limit: int the max number of active short-term memory, default is 10
    short_term_buffer: int the buffer for flushing the short-term active memory to a long-term storage
    long_term_strategy: Literal["messages" | "summarize"]: choose messages will convert the short-term memory to a long-term memory, summarize will convert the short-term memories to one single summarized long-term memories
    stores: List[MemoryStore]
        {
            "name": str: the store name that is created by default or otherwise customized,
            "memory_type": MemoryType,
            "store_config: {
                wildcards that can be read by the memory store -> see instruction in the memory store.
            },
        }
    """

    @classmethod
    def from_config(cls, config: dict) -> "DefaultMemoryManager":
        short_term_limit = config.get("short_term_limit") or DEFAULT_SHORT_TERM_LIMIT
        long_term_strategy = (
            config.get("long_term_strategy") or DEFAULT_LONG_TERM_STRATEGY
        )
        if long_term_strategy not in ["messages", "summarize"]:
            raise ValueError(
                "long_term_strategy must be one of 'messages', 'summarize'"
            )

        short_term_max = config.get("short_term_max") or DEFAULT_SHORT_TERM_MAX
        stores = config.get("stores") or []

        short_term_store = None
        long_term_store = None

        for store in stores:
            memory_type = store.get("memory_type")
            store_name = store.get("name")

            if not store_name:
                raise ValueError("Missing store name.")

            if not isinstance(memory_type, MemoryType):
                raise ValueError("Memory type must be one of the MemoryType")

            store_cls = MemoryStoreRegistry.get(store_name)

            if memory_type == MemoryType.SHORT_TERM:
                short_term_store = store_cls.from_config(store["store_config"])
            elif memory_type == MemoryType.LONG_TERM:
                long_term_store = store_cls.from_config(store["store_config"])
            else:
                raise ValueError(
                    "Manager only supports long-term and short-term memories right now. For future releases, please check back on the repo."
                )

        return cls(
            short_term_store=short_term_store,
            long_term_store=long_term_store,
            short_term_limit=short_term_limit,
            max_short_term_memories=short_term_max,
        )

    """Main memory manager that orchestrates different memory stores and strategies."""

    def __init__(
        self,
        short_term_store: Optional[BaseMemoryStore] = None,
        long_term_store: Optional[BaseMemoryStore] = None,
        short_term_limit: int = DEFAULT_SHORT_TERM_LIMIT,
        max_short_term_memories: int = DEFAULT_SHORT_TERM_MAX,
        memory_decay_hours: int = 24,
    ):
        # Data validation
        self.short_term_store = short_term_store
        self.long_term_store = long_term_store
        self.short_term_limit = short_term_limit

        # buffer number set to 50%.
        self.max_short_term_memories = max_short_term_memories
        self.memory_decay_hours = memory_decay_hours

    async def add_memory(
        self,
        message: BaseMessage,
        *,
        session_id: str,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        importance_score: float = 0.5,
        memory_type: MemoryType = MemoryType.SHORT_TERM,
    ) -> None:

        entry = self._entry_from_message(
            message,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
            importance_score=importance_score,
            memory_type=memory_type,
        )

        await self.short_term_store.awrite_memory([entry])

    async def manage_memory_size(self) -> None:
        """Manage memory size by moving old memories to long-term storage."""
        short_memories = await self.short_term_store.aread_memories(
            memory_type=MemoryType.SHORT_TERM,
            limit=self.max_short_term_memories * 2,  # Get all short-term memories
        )
        if len(short_memories) > self.max_short_term_memories:
            # Sort by importance and age
            short_memories.sort(
                key=lambda x: (x.importance_score, x.timestamp), reverse=True
            )

            # Keep the most important/recent ones in short-term
            to_move = short_memories[self.short_term_limit :]

            # Wrap in a background task that deletes only ON SUCCESS
            async def safe_transfer():
                try:
                    await self.long_term_store.awrite_memory(to_move)
                    for memory in to_move:
                        await self.short_term_store.adelete_memory(memory.record_id)
                except Exception as e:
                    logger.error(f"FAILED to move memories to LTM: {e}")

            asyncio.create_task(safe_transfer())

    async def retrieve_memories(
        self,
        query: str,
        *,
        session_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 10,
        include_short_term: bool = True,
        include_long_term: bool = True,
    ):
        """Retrieve relevant memories based on query."""
        all_memories: list[MemoryEntry] = []

        st_types, lt_types = self._resolve_memory_types(
            memory_types,
            include_short_term=include_short_term,
            include_long_term=include_long_term,
        )

        read_kwargs = self._construct_read_kwargs(
            query,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
            limit=limit,
        )

        tasks = []
        if st_types and self.short_term_store:
            tasks.extend(
                self.short_term_store.aread_memories(memory_type=mt, **read_kwargs)
                for mt in st_types
            )
        if lt_types and self.long_term_store:
            tasks.extend(
                self.long_term_store.aread_memories(memory_type=mt, **read_kwargs)
                for mt in lt_types
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_memories: list[MemoryEntry] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"Memory store read failed: {r}")
                continue
            all_memories.extend(r or [])

        # Sort by relevance (importance + recency)
        all_memories.sort(key=self._rank_memory_relevancy, reverse=True)
        return all_memories[:limit]

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about current memory usage."""
        short_term_count = len(self.short_term_store.read_memories(limit=1000))
        long_term_count = len(self.long_term_store.read_memories(limit=1000))

        return {
            "short_term_memories": short_term_count,
            "long_term_memories": long_term_count,
            "total_memories": short_term_count + long_term_count,
        }

    def _construct_read_kwargs(
        self,
        query: str,
        *,
        session_id: str | None,
        task_id: str | None,
        user_id: str | None,
        metadata: dict[str, Any] | None,
        limit: int,
    ) -> dict[str, Any]:
        """Build the kwargs passed to every store's aread_memories call.

        Stores receive the same kwargs and decide what to use. Override this
        method to add custom params (e.g., namespace, tenant_id) across all
        stores.
        """
        return dict(
            query=query,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
            limit=limit,
        )

    def _resolve_memory_types(
        self,
        memory_types: list[MemoryType] | None,
        include_short_term: bool,
        include_long_term: bool,
    ) -> tuple[list[MemoryType], list[MemoryType]]:
        """Split requested types into (short_term_types, long_term_types)."""
        if memory_types:
            st_types = [mt for mt in memory_types if mt == MemoryType.SHORT_TERM]
            lt_types = [mt for mt in memory_types if mt != MemoryType.SHORT_TERM]
        else:
            st_types = [MemoryType.SHORT_TERM]
            lt_types = list(DEFAULT_LONG_TERM_TYPES)

        if not include_short_term:
            st_types = []
        if not include_long_term:
            lt_types = []
        return st_types, lt_types

    def _entry_from_message(
        self,
        message: BaseMessage,
        *,
        session_id: str,
        task_id: Optional[str],
        user_id: Optional[str],
        metadata: Optional[dict[str, Any]],
        importance_score: float,
        memory_type: MemoryType,
    ) -> MemoryEntry:
        """Convert a LangChain message to a MemoryEntry."""
        role_map = {AIMessage: "agent", HumanMessage: "human", ToolMessage: "tool"}
        role = role_map.get(type(message))
        if not role:
            raise ValueError(
                f"Unsupported message type: {type(message).__name__}. "
                "Expected AIMessage, HumanMessage, or ToolMessage."
            )

        entry_metadata = {
            **(metadata or {}),
            **getattr(message, "response_metadata", {}),
            "role": role,
        }

        return MemoryEntry(
            content=message.content,
            session_id=session_id,
            task_id=task_id,
            user_id=user_id,
            metadata=entry_metadata,
            timestamp=datetime.now(),
            memory_type=memory_type,
            importance_score=importance_score,
        )

    def _rank_memory_relevancy(self, memory: MemoryEntry) -> float:
        return (
            memory.importance_score * 0.7 + self.calculate_recency_score(memory) * 0.3
        )

    @staticmethod
    def calculate_recency_score(memory: MemoryEntry) -> float:
        """Calculate a recency score (0-1) based on how recent the memory is."""
        now = datetime.now()
        age_hours = (now - memory.timestamp).total_seconds() / 3600

        if age_hours <= 1:
            return 1.0
        elif age_hours >= 24:
            return 0.1
        else:
            return 1.0 - (age_hours / 24.0) * 0.9
