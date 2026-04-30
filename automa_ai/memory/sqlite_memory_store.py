import json
import sqlite3
from datetime import datetime
from typing import Optional, List

from automa_ai.memory.memory_stores import BaseMemoryStore
from automa_ai.memory.memory_types import MemoryEntry, MemoryType


class SQLiteMemoryStore(BaseMemoryStore):
    """SQLite-based persistent memory storage."""

    @classmethod
    def from_config(cls, config: dict) -> "BaseMemoryStore":
        """
        store: {
            "db_path": str, Path to the database file
        }
        """
        db_path = config.get("db_path")
        if not db_path:
            raise ValueError("db_path must be defined for SQLiteMemoryStore.")

        return cls(db_path=db_path)

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    timestamp REAL,
                    memory_type TEXT,
                    importance_score REAL,
                    access_count INTEGER,
                    last_accessed REAL
                )
            """)
            conn.commit()

    def write_memory(self, entries: List[MemoryEntry]) -> None:
        """Write a memory entry to SQLite storage."""

        query = """
            INSERT INTO memories (
                record_id, session_id, user_id, content, metadata,
                timestamp, memory_type, importance_score, access_count, last_accessed
            )
            VALUES (
                :record_id, :session_id, :user_id, :content, :metadata,
                :timestamp, :memory_type, :importance_score, :access_count, :last_accessed
            )
        """

        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(query, [e.to_db_dict() for e in entries])
            conn.commit()

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
        """Read memory entries from SQLite storage."""
        sql = "SELECT * FROM memories"
        params = []
        conditions = []

        for key, value in [
            ("session_id", session_id),
            ("user_id", user_id),
            ("memory_type", memory_type.value if memory_type else None),
        ]:
            if value:
                conditions.append(f"{key} = ?")
                params.append(value)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        memories = []
        for row in rows:
            entry = MemoryEntry.from_db_row(row)
            memories.append(entry)

        return memories

    def delete_memory(self, record_id: str) -> bool:
        """Delete a specific memory entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
            conn.commit()
            return cursor.rowcount > 0

    def clear_memories(self, memory_type: Optional[MemoryType] = None) -> None:
        """Clear memories of a specific type or all memories."""
        with sqlite3.connect(self.db_path) as conn:
            if memory_type is None:
                conn.execute("DELETE FROM memories")
            else:
                conn.execute(
                    "DELETE FROM memories WHERE memory_type = ?", (memory_type.value,)
                )
            conn.commit()
