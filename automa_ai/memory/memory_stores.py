import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional, List
from automa_ai.memory.memory_types import MemoryEntry, MemoryType


class BaseMemoryStore(ABC):
    """Abstract base class for memory stores."""

    @classmethod
    @abstractmethod
    def from_config(cls, config: dict) -> "BaseMemoryStore":
        raise NotImplementedError

    @abstractmethod
    def write_memory(self, entries: List[MemoryEntry]) -> None:
        """Write a memory entry to storage."""
        pass

    async def awrite_memory(self, entries: List[MemoryEntry]) -> None:
        """Asynchronous Write a memory entry to storage."""
        await asyncio.to_thread(self.write_memory, entries)

    @abstractmethod
    def read_memories(
        self,
        query: Optional[str] = None,
        *,
        limit: int = 10,
        **kwargs,
    ) -> List[MemoryEntry]:
        """Read memory entries from storage.

        Standard kwargs: session_id, task_id, user_id, metadata, memory_type.
        """
        pass

    async def aread_memories(
        self,
        query: Optional[str] = None,
        *,
        limit: int = 10,
        **kwargs,
    ) -> List[MemoryEntry]:
        memory_list = await asyncio.to_thread(
            self.read_memories, query, limit=limit, **kwargs
        )
        return memory_list

    @abstractmethod
    def delete_memory(self, record_id: str) -> bool:
        """Delete a specific memory entry."""
        pass

    async def adelete_memory(self, record_id: str) -> bool:
        """Asynchronous Delete a specific memory entry."""
        delete = await asyncio.to_thread(self.delete_memory, record_id)
        return delete

    @abstractmethod
    def clear_memories(self, memory_type: Optional[MemoryType] = None) -> None:
        """Clear memories of a specific type or all memories."""
        pass


class MemoryStoreRegistry:
    _stores: dict[str, type[BaseMemoryStore]] = {}

    @classmethod
    def register(cls, name: str, store_cls: type[BaseMemoryStore]):
        if not issubclass(store_cls, BaseMemoryStore):
            raise TypeError("MemoryStore must subclass BaseMemoryStore")
        cls._stores[name] = store_cls

    @classmethod
    def get(cls, name: str) -> type[BaseMemoryStore]:
        if name not in cls._stores:
            raise KeyError(f"Unknown memory store: {name}")
        return cls._stores[name]
