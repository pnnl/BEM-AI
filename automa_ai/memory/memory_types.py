from datetime import datetime
import json
import uuid
from enum import Enum
from typing import Dict, Any, Mapping

from pydantic import BaseModel, Field


class MemoryType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"

class MemoryEntry(BaseModel):
    id: int | None = Field(
        default=None,
        description="Index for this memory entry."
    )

    record_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for memory entry."
    )

    session_id: str = Field(
        default_factory=lambda:str(uuid.uuid4()),
        description="Unique identifier for this session entry."
    )

    task_id: str = Field(
        default=None,
        description="Unique identifier for the task associated with this memory entry."
    )

    user_id: str = Field(
        default=None,
        description="Unique identifier for the user."
    )

    content: str = Field(
        default="",
        description="The textual message or information stored in memory."
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Additional structured metadata associated with the memory entry, "
            "such as source, tags, agent name, or embedding-related information."
        )
    )

    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="The time when this memory entry was created."
    )

    memory_type: MemoryType = Field(
        default=MemoryType.SHORT_TERM,
        description="Classification of the memory (e.g., short_term, long_term, episodic)."
    )

    importance_score: float = Field(
        default=0.5,
        description=(
            "Relative importance of this memory on a scale from 0.0 to 1.0. "
            "Used to influence retention, retrieval, or summarization."
        )
    )

    access_count: int = Field(
        default=0,
        description="Number of times this memory entry has been accessed or retrieved."
    )

    last_accessed: datetime = Field(
        default_factory=datetime.now,
        description="The most recent time this memory entry was accessed."
    )

    @classmethod
    def from_db_row(cls, row: Mapping[str, Any]) -> "MemoryEntry":
        return cls(
            id=row["id"],
            record_id=row["record_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            user_id=row["user_id"],
            content=row["content"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            timestamp=datetime.fromtimestamp(row["timestamp"]),
            memory_type=MemoryType(row["memory_type"]),
            importance_score=row["importance_score"],
            access_count=row["access_count"],
            last_accessed=datetime.fromtimestamp(row["last_accessed"]),
        )
    
    def to_db_tuple(self) -> tuple:
        return (
            self.id,
            self.record_id,
            self.session_id,
            self.task_id,
            self.user_id,
            self.content,
            json.dumps(self.metadata),
            self.timestamp.timestamp(),
            self.memory_type.value,
            self.importance_score,
            self.access_count,
            self.last_accessed.timestamp(),
        )