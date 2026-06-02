import sqlite3
from datetime import datetime, timezone

import pytest

from automa_ai.token_management import (
    SQLiteTokenUsageStore,
    TokenUsageRecord,
    TokenUsageStore,
    TokenUsageStoreRegistry,
    TokenUsageSummary,
    create_token_usage_store,
    register_token_usage_store,
)


class DummyTokenUsageStore(TokenUsageStore):
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.records: list[TokenUsageRecord] = []

    @classmethod
    def from_config(cls, config):
        if not isinstance(config, dict):
            config = config.model_dump()
        return cls(table_name=config["table_name"])

    def write_usage(self, record: TokenUsageRecord) -> None:
        self.records.append(record)

    def summarize_usage(
        self,
        *,
        user_id: str | None = None,
        context_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> TokenUsageSummary:
        return TokenUsageSummary()


class DefaultConfigTokenUsageStore(TokenUsageStore):
    def __init__(self, table_name: str):
        self.table_name = table_name

    def write_usage(self, record: TokenUsageRecord) -> None:
        return None

    def summarize_usage(
        self,
        *,
        user_id: str | None = None,
        context_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> TokenUsageSummary:
        return TokenUsageSummary()


def test_sqlite_token_usage_store_records_and_summarizes(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))

    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-1",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
        )
    )
    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-2",
            task_id="task-2",
            input_tokens=3,
            output_tokens=4,
            total_tokens=7,
        )
    )

    user_summary = store.summarize_usage(user_id="user-1")
    session_summary = store.summarize_usage(context_id="session-1")

    assert user_summary.total_tokens == 22
    assert user_summary.num_calls == 2
    assert session_summary.input_tokens == 10
    assert session_summary.output_tokens == 5
    assert session_summary.total_tokens == 15


def test_sqlite_token_usage_store_normalizes_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    store = SQLiteTokenUsageStore(db_path="usage.db")

    assert store.db_path == str(tmp_path / "usage.db")


def test_sqlite_token_usage_store_serializes_non_json_metadata(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))

    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-1",
            total_tokens=1,
            metadata={"path": tmp_path},
        )
    )

    assert store.summarize_usage(context_id="session-1").total_tokens == 1


def test_sqlite_token_usage_store_summarizes_time_window(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))
    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-1",
            total_tokens=10,
            created_at=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        )
    )
    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-2",
            total_tokens=20,
            created_at=datetime(2026, 2, 1, 12, tzinfo=timezone.utc),
        )
    )

    summary = store.summarize_usage(
        user_id="user-1",
        start_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    assert summary.total_tokens == 20
    assert summary.num_calls == 1


def test_sqlite_token_usage_store_creates_time_window_indexes(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))

    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()

    index_names = {row[0] for row in rows}
    assert "idx_token_usage_user_created_at" in index_names
    assert "idx_token_usage_context_created_at" in index_names
    assert "idx_token_usage_created_at" in index_names


def test_custom_token_usage_store_registry_builds_registered_store():
    original_stores = dict(TokenUsageStoreRegistry._stores)
    try:
        register_token_usage_store("dummy", DummyTokenUsageStore)

        store = create_token_usage_store(
            {
                "backend": "dummy",
                "table_name": "token-ledger",
            }
        )

        assert isinstance(store, DummyTokenUsageStore)
        assert store.table_name == "token-ledger"
    finally:
        TokenUsageStoreRegistry._stores = original_stores


def test_custom_token_usage_store_can_use_default_from_config():
    original_stores = dict(TokenUsageStoreRegistry._stores)
    try:
        register_token_usage_store("default_config", DefaultConfigTokenUsageStore)

        store = create_token_usage_store(
            {
                "backend": "default_config",
                "table_name": "token-ledger",
            }
        )

        assert isinstance(store, DefaultConfigTokenUsageStore)
        assert store.table_name == "token-ledger"
    finally:
        TokenUsageStoreRegistry._stores = original_stores


def test_token_usage_store_registry_rejects_non_store():
    with pytest.raises(
        TypeError,
        match=r"TokenUsageStore must subclass TokenUsageStore; got <class 'object'>",
    ):
        TokenUsageStoreRegistry.register("bad", object)


def test_token_usage_store_registry_rejects_non_class():
    store = DefaultConfigTokenUsageStore(table_name="token-ledger")

    with pytest.raises(
        TypeError,
        match=r"TokenUsageStore must be registered with a class; got .*"
        r"DefaultConfigTokenUsageStore.*type=DefaultConfigTokenUsageStore",
    ):
        TokenUsageStoreRegistry.register("bad", store)


def test_create_token_usage_store_raises_value_error_for_unknown_backend():
    with pytest.raises(
        ValueError,
        match="Unknown token usage store backend: missing. Known backends:",
    ):
        create_token_usage_store({"backend": "missing"})


def test_sqlite_token_usage_store_requires_db_path():
    with pytest.raises(ValueError, match="db_path must be defined"):
        create_token_usage_store({"backend": "sqlite"})
