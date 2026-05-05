from pathlib import Path
from typing import Optional, Dict, List, Any

from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings

from automa_ai.memory.memory_stores import BaseMemoryStore
from automa_ai.memory.memory_types import MemoryEntry, MemoryType


class ChromaVectorMemoryStore(BaseMemoryStore):
    """Vector-based memory storage using embeddings for semantic search."""

    @classmethod
    def from_config(cls, config: dict) -> "BaseMemoryStore":
        """
        store: {
            "db_path": str, Path to the database file,
            "collection_name": str, optional
        }
        """
        db_path = config.get("db_path")
        if not db_path:
            raise ValueError("db_path must be defined for ChromaVectorMemoryStore.")

        return cls(persist_directory=db_path)

    def __init__(
        self,
        persist_directory: str,
        collection_name: str = "memory_store",
        embeddings: Optional[Embeddings] = None,
    ):
        self.embeddings = embeddings
        self.collection_name = collection_name
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(exist_ok=True)

        # Initialize vector store
        self.vectorstore = Chroma(
            collection_name=collection_name,
            embedding_function=self.embeddings,
            persist_directory=str(self.persist_directory),
        )

        # Keep a mapping of document IDs to memory entries
        self.memory_mapping: Dict[str, MemoryEntry] = {}

    def write_memory(self, entries: List[MemoryEntry]) -> None:
        """Write a memory entry to vector storage."""
        # Add to vector store
        """Write multiple memory entries to Chroma vector store (bulk insert)."""
        if not entries:
            return  # nothing to insert

        texts = [entry.content for entry in entries]
        metadatas = [
            {
                **(entry.metadata or {}),
                "record_id": entry.record_id,
                "session_id": entry.session_id,
                "task_id": entry.task_id,
                "user_id": entry.user_id,
                "timestamp": entry.timestamp.isoformat(),
                "memory_type": entry.memory_type.value,
                "importance_score": entry.importance_score,
                "access_count": entry.access_count,
                "last_accessed": entry.last_accessed.isoformat(),
            }
            for entry in entries
        ]
        record_ids = [entry.record_id for entry in entries]

        # Add all entries at once
        self.vectorstore.add_texts(texts=texts, metadatas=metadatas, ids=record_ids)

        # Keep in memory mapping
        for entry in entries:
            self.memory_mapping[entry.record_id] = entry

    def read_memories(
        self,
        query: Optional[str] = None,
        *,
        limit: int = 10,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        **kwargs,
    ) -> List[MemoryEntry]:
        """Read memory entries using semantic search."""
        filter_kwargs = dict(kwargs)
        metadata = filter_kwargs.pop("metadata", None)
        filter_dict = build_chroma_filter(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            **filter_kwargs,
        )
        if query:
            # Semantic search
            if filter_dict:
                results = self.vectorstore.similarity_search_with_score(
                    query=query,
                    k=1000,  # Get more results to filter
                    filter=filter_dict,
                )
            else:
                results = self.vectorstore.similarity_search_with_score(
                    query=query,
                    k=1000,  # Get more results to filter
                )

            memories = []
            for doc, score in results:
                record_id = doc.metadata.get("record_id") or getattr(doc, "id", None)
                if record_id in self.memory_mapping:
                    memory = self.memory_mapping[record_id]
                    # Filter by memory type if specified
                    if memory_type is None or memory.memory_type == memory_type:
                        memories.append(memory)

                if len(memories) >= limit:
                    break

            return memories
        else:
            # Return recent memories
            memories = list(self.memory_mapping.values())
            memories = [
                memory
                for memory in memories
                if _matches_memory_filters(
                    memory,
                    session_id=session_id,
                    task_id=kwargs.get("task_id"),
                    user_id=user_id,
                    metadata=kwargs.get("metadata"),
                )
            ]
            if memory_type:
                memories = [m for m in memories if m.memory_type == memory_type]

            memories.sort(key=lambda x: x.timestamp, reverse=True)
            return memories[:limit]

    def delete_memory(self, record_id: str) -> bool:
        """Delete a specific memory entry."""
        if record_id in self.memory_mapping:
            # Remove from vector store
            self.vectorstore.delete([record_id])
            # Remove from mapping
            del self.memory_mapping[record_id]
            return True
        return False

    def clear_memories(self, memory_type: Optional[MemoryType] = None) -> None:
        """Clear memories of a specific type or all memories."""
        if memory_type is None:
            # Clear everything
            self.vectorstore.delete_collection()
            self.memory_mapping.clear()
            # Reinitialize
            self.vectorstore = Chroma(
                collection_name=self.collection_name,
                embedding_function=self.embeddings,
                persist_directory=str(self.persist_directory),
            )
        else:
            # Clear specific memory type
            to_delete = [
                mid
                for mid, memory in self.memory_mapping.items()
                if memory.memory_type == memory_type
            ]
            for mid in to_delete:
                self.delete_memory(mid)


def _matches_memory_filters(
    memory: MemoryEntry,
    *,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> bool:
    if session_id is not None and memory.session_id != session_id:
        return False
    if task_id is not None and memory.task_id != task_id:
        return False
    if user_id is not None and memory.user_id != user_id:
        return False
    if metadata:
        memory_metadata = memory.metadata or {}
        return all(memory_metadata.get(key) == value for key, value in metadata.items())
    return True


def build_chroma_filter(
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    merged = {}
    # Merge all filters, with canonical fields taking precedence only when explicitly provided.
    if kwargs:
        merged.update(kwargs)
    if metadata:
        merged.update(metadata)
    if session_id is not None:
        merged["session_id"] = session_id
    if task_id is not None:
        merged["task_id"] = task_id
    if user_id is not None:
        merged["user_id"] = user_id

    clauses = [
        {field: {"$eq": value}} for field, value in merged.items() if value is not None
    ]

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}
