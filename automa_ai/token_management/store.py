from __future__ import annotations

import asyncio
import json
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automa_ai.config.token_budget import TokenUsageStoreConfig


@dataclass(frozen=True)
class TokenUsageRecord:
    """One persisted model-call usage event."""

    agent_name: str | None
    model: str | None
    model_provider: str | None
    user_id: str | None
    context_id: str | None
    task_id: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TokenUsageSummary:
    """Aggregated token usage for a user, session, or whole store."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    num_calls: int = 0


class TokenUsageStore(ABC):
    """Persistence boundary for token usage records.

    Custom backends should implement this interface and keep the same
    user/context/task identifiers, so budget enforcement remains unchanged.
    """

    @classmethod
    def from_config(
        cls,
        config: TokenUsageStoreConfig | dict[str, Any],
    ) -> "TokenUsageStore":
        """Build a store instance from framework config data."""
        if isinstance(config, TokenUsageStoreConfig):
            config = config.model_dump(exclude_none=True)
        kwargs = dict(config)
        kwargs.pop("backend", None)
        return cls(**kwargs)

    @abstractmethod
    def write_usage(self, record: TokenUsageRecord) -> None:
        """Persist one model-call usage event."""
        raise NotImplementedError

    async def awrite_usage(self, record: TokenUsageRecord) -> None:
        """Async wrapper for stores that only provide sync persistence."""
        await asyncio.to_thread(self.write_usage, record)

    @abstractmethod
    def summarize_usage(
        self,
        *,
        user_id: str | None = None,
        context_id: str | None = None,
    ) -> TokenUsageSummary:
        """Return aggregate usage for the requested user and/or context."""
        raise NotImplementedError

    async def asummarize_usage(
        self,
        *,
        user_id: str | None = None,
        context_id: str | None = None,
    ) -> TokenUsageSummary:
        """Async wrapper for aggregate usage reads."""
        return await asyncio.to_thread(
            self.summarize_usage,
            user_id=user_id,
            context_id=context_id,
        )


class SQLiteTokenUsageStore(TokenUsageStore):
    """SQLite implementation of token usage persistence."""

    @classmethod
    def from_config(cls, config: TokenUsageStoreConfig | dict[str, Any]):
        """Build a SQLite store from YAML or direct config data."""
        if not isinstance(config, TokenUsageStoreConfig):
            config = TokenUsageStoreConfig.model_validate(config)
        if config.db_path is None:
            raise ValueError("db_path must be defined for SQLiteTokenUsageStore.")
        return cls(db_path=config.db_path)

    def __init__(self, db_path: str):
        resolved_db_path = Path(db_path).expanduser().resolve()
        self.db_path = str(resolved_db_path)
        db_parent = resolved_db_path.parent
        db_parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived SQLite connection."""
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        """Create the token usage table and lookup indexes if needed."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT,
                    model TEXT,
                    model_provider TEXT,
                    user_id TEXT,
                    context_id TEXT,
                    task_id TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_usage_user_id "
                "ON token_usage(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_usage_context_id "
                "ON token_usage(context_id)"
            )
            conn.commit()

    def write_usage(self, record: TokenUsageRecord) -> None:
        """Insert one token usage record."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO token_usage (
                    agent_name,
                    model,
                    model_provider,
                    user_id,
                    context_id,
                    task_id,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    created_at,
                    metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.agent_name,
                    record.model,
                    record.model_provider,
                    record.user_id,
                    record.context_id,
                    record.task_id,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    record.created_at.isoformat(),
                    json.dumps(record.metadata, default=str),
                ),
            )
            conn.commit()

    def summarize_usage(
        self,
        *,
        user_id: str | None = None,
        context_id: str | None = None,
    ) -> TokenUsageSummary:
        """Aggregate token usage with optional user/session filters."""
        sql = """
            SELECT
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(total_tokens), 0),
                COUNT(*)
            FROM token_usage
        """
        conditions: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if context_id is not None:
            conditions.append("context_id = ?")
            params.append(context_id)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()

        return TokenUsageSummary(
            input_tokens=int(row[0] or 0),
            output_tokens=int(row[1] or 0),
            total_tokens=int(row[2] or 0),
            num_calls=int(row[3] or 0),
        )


class TokenUsageStoreRegistry:
    """Registry for token usage persistence backends."""

    _stores: dict[str, type[TokenUsageStore]] = {}

    @classmethod
    def register(cls, name: str, store_cls: type[TokenUsageStore]) -> None:
        """Register a token usage store class under a config backend name."""
        if not isinstance(store_cls, type):
            raise TypeError(
                "TokenUsageStore must be registered with a class; "
                f"got {store_cls!r} (type={type(store_cls).__name__})"
            )
        if not issubclass(store_cls, TokenUsageStore):
            raise TypeError(
                "TokenUsageStore must subclass TokenUsageStore; "
                f"got {store_cls!r} (type={type(store_cls).__name__})"
            )
        cls._stores[name] = store_cls

    @classmethod
    def get(cls, name: str) -> type[TokenUsageStore]:
        """Return the registered store class for a backend name."""
        try:
            return cls._stores[name]
        except KeyError as exc:
            known = ", ".join(sorted(cls._stores)) or "<none>"
            raise KeyError(
                f"Unknown token usage store backend: {name}. "
                f"Known backends: {known}"
            ) from exc

    @classmethod
    def list(cls) -> list[str]:
        """List registered token usage store backend names."""
        return sorted(cls._stores)


TokenUsageStoreRegistry.register("sqlite", SQLiteTokenUsageStore)


def register_token_usage_store(
    name: str,
    store_cls: type[TokenUsageStore],
) -> None:
    """Register a project-provided token usage store backend."""
    TokenUsageStoreRegistry.register(name, store_cls)


def create_token_usage_store(
    config: TokenUsageStoreConfig | dict[str, Any] | None,
) -> TokenUsageStore | None:
    """Create the configured token usage store.

    The factory lives at the interface boundary so future backends, such as
    DynamoDB, can be registered here without changing the middleware or agent
    runtime integration.
    """
    if config is None:
        return None
    if not isinstance(config, TokenUsageStoreConfig):
        config = TokenUsageStoreConfig.model_validate(config)
    try:
        store_cls = TokenUsageStoreRegistry.get(config.backend)
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        raise ValueError(message) from exc
    return store_cls.from_config(config)
