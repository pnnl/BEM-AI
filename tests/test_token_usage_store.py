from automa_ai.token_management import SQLiteTokenUsageStore, TokenUsageRecord


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
