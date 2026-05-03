import json
import sqlite3
from datetime import datetime
from typing import Any, Optional, List

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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT,
                    session_id TEXT NOT NULL,
                    task_id TEXT,
                    user_id TEXT,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    timestamp REAL,
                    memory_type TEXT,
                    importance_score REAL,
                    access_count INTEGER,
                    last_accessed REAL
                )
            """
            )
            self._ensure_column(conn, "record_id", "TEXT")
            self._ensure_column(conn, "task_id", "TEXT")
            conn.commit()

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection, column_name: str, definition: str
    ) -> None:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()
        }
        if column_name not in columns:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {column_name} {definition}")

    def write_memory(self, entries: List[MemoryEntry]) -> None:
        """Write a memory entry to SQLite storage."""

        with sqlite3.connect(self.db_path) as conn:
            data_to_insert = [
                (
                    entry.record_id,
                    entry.session_id,
                    entry.task_id,
                    entry.user_id,
                    entry.content,
                    json.dumps(entry.metadata),
                    entry.timestamp.timestamp(),
                    entry.memory_type.value,
                    entry.importance_score,
                    entry.access_count,
                    entry.last_accessed.timestamp(),
                )
                for entry in entries
            ]

            conn.executemany(
                """
                        INSERT INTO memories 
                        (record_id, session_id, task_id, user_id, content, metadata, timestamp, memory_type, importance_score, access_count, last_accessed)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                data_to_insert,
            )

    def read_memories(
        self,
        query: Optional[str] = None,
        *,
        limit: int = 10,
        session_id: Optional[str] = None,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        **kwargs,
    ) -> List[MemoryEntry]:
        """Read memory entries from SQLite storage."""
        sql = """
            SELECT id, record_id, session_id, task_id, user_id, content, metadata,
                   timestamp, memory_type, importance_score, access_count, last_accessed
            FROM memories
        """
        params: list[Any] = []
        conditions = []

        for key, value in [
            ("session_id", session_id),
            ("task_id", task_id or kwargs.get("task_id")),
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
            entry = MemoryEntry(
                id=row[0],
                record_id=row[1] or str(row[0]),
                session_id=row[2],
                task_id=row[3],
                user_id=row[4],
                content=row[5],
                metadata=json.loads(row[6]) if row[6] else {},
                timestamp=datetime.fromtimestamp(row[7]),
                memory_type=MemoryType(row[8]),
                importance_score=row[9],
                access_count=row[10],
                last_accessed=datetime.fromtimestamp(row[11]),
            )
            memories.append(entry)

        return memories

    def delete_memory(self, record_id: str) -> bool:
        """Delete a specific memory entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM memories WHERE record_id = ?",
                (record_id,),
            )
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
