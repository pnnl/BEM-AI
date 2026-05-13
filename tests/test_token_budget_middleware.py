import pytest
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage

from automa_ai.config.token_budget import TokenBudgetConfig
import automa_ai.token_management.middleware as middleware_module
from automa_ai.token_management import (
    SQLiteTokenUsageStore,
    TokenBudgetExceededError,
    TokenBudgetMiddleware,
    TokenUsageRecord,
)


class DummyRuntime:
    def __init__(self):
        self.config = {
            "configurable": {
                "thread_id": "agent:session-1",
                "automa_context_id": "session-1",
                "actor_id": "user-1",
                "task_id": "task-1",
            }
        }


def test_token_budget_middleware_trims_messages_and_sets_output_limit():
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(
            max_input_tokens=30,
            reserve_output_tokens=5,
            max_output_tokens=12,
        ),
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[
            HumanMessage(content="old " * 100),
            HumanMessage(content="new"),
        ],
        runtime=DummyRuntime(),
    )

    def handler(scoped_request):
        assert len(scoped_request.messages) == 1
        assert scoped_request.messages[0].content == "new"
        assert scoped_request.model_settings["max_tokens"] == 12
        return ModelResponse(result=[AIMessage(content="ok")])

    middleware.wrap_model_call(request, handler)


def test_token_budget_middleware_blocks_exhausted_session(tmp_path):
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
        )
    )
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(max_session_tokens=10),
        usage_store=store,
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    with pytest.raises(TokenBudgetExceededError, match="Session token budget exceeded"):
        middleware.wrap_model_call(
            request,
            lambda scoped_request: ModelResponse(result=[AIMessage(content="ok")]),
        )


def test_token_budget_middleware_records_usage(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(),
        usage_store=store,
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(
            result=[
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 11,
                        "output_tokens": 4,
                        "total_tokens": 15,
                    },
                    response_metadata={
                        "model": "gpt-test",
                        "model_provider": "openai",
                    },
                )
            ]
        ),
    )

    summary = store.summarize_usage(context_id="session-1")

    assert summary.total_tokens == 15
    assert summary.num_calls == 1


def test_token_budget_middleware_reads_langgraph_config(monkeypatch, tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))
    monkeypatch.setattr(
        middleware_module,
        "get_config",
        lambda: {
            "configurable": {
                "thread_id": "agent:session-from-config",
                "actor_id": "user-from-config",
                "task_id": "task-from-config",
            }
        },
    )
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(),
        usage_store=store,
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=object(),
    )

    middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(
            result=[
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "total_tokens": 5,
                    },
                )
            ]
        ),
    )

    assert store.summarize_usage(context_id="session-from-config").total_tokens == 5
    assert store.summarize_usage(user_id="user-from-config").total_tokens == 5
