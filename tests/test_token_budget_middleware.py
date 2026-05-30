from datetime import datetime, timedelta, timezone

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
    TokenUsageSummary,
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


class FailingUsageStore:
    def write_usage(self, record):
        raise RuntimeError("write failed")

    async def awrite_usage(self, record):
        raise RuntimeError("async write failed")

    def summarize_usage(self, **kwargs):
        raise AssertionError("summarize_usage should not be called")

    async def asummarize_usage(self, **kwargs):
        raise AssertionError("asummarize_usage should not be called")


class LegacySummaryUsageStore:
    def write_usage(self, record):
        return None

    def summarize_usage(self, *, user_id=None, context_id=None):
        return TokenUsageSummary()


@pytest.mark.parametrize(
    "field_name",
    [
        "max_input_tokens",
        "max_output_tokens",
        "max_model_calls_per_turn",
        "max_tool_calls_per_turn",
        "max_session_tokens",
        "max_user_tokens",
        "summarize_when_tokens",
    ],
)
def test_token_budget_config_rejects_zero_for_optional_limits(field_name):
    with pytest.raises(ValueError, match=f"{field_name} must be greater than 0"):
        TokenBudgetConfig(**{field_name: 0})


def test_token_budget_config_validates_rolling_window_seconds():
    with pytest.raises(ValueError, match="rolling_seconds must be greater than 0"):
        TokenBudgetConfig(
            max_user_tokens=100,
            user_token_window={"period": "rolling"},
        )


def test_token_budget_config_rejects_unknown_window_timezone():
    with pytest.raises(
        ValueError,
        match=(
            "Unknown token budget timezone: 'Not/AZone'. " "Use an IANA timezone name"
        ),
    ):
        TokenBudgetConfig(
            max_user_tokens=100,
            user_token_window={
                "period": "calendar_month",
                "timezone": "Not/AZone",
            },
        )


def test_token_budget_config_rejects_unknown_window_period():
    with pytest.raises(
        ValueError,
        match=(
            "Unsupported token budget window period: 'weekly'. "
            "Use one of: calendar_day, calendar_month, lifetime, rolling."
        ),
    ):
        TokenBudgetConfig(
            max_user_tokens=100,
            user_token_window={"period": "weekly"},
        )


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


def test_token_budget_middleware_omits_window_kwargs_for_lifetime_budget():
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(max_session_tokens=10),
        usage_store=LegacySummaryUsageStore(),
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    response = middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(result=[AIMessage(content="ok")]),
    )

    assert response.result[0].content == "ok"


def test_token_budget_middleware_applies_session_calendar_day_window(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))
    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-old",
            total_tokens=10,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(
            max_session_tokens=10,
            session_token_window={
                "period": "calendar_day",
                "timezone": "UTC",
            },
        ),
        usage_store=store,
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    response = middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(result=[AIMessage(content="ok")]),
    )

    assert response.result[0].content == "ok"

    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-current",
            total_tokens=10,
            created_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(TokenBudgetExceededError, match="Session token budget exceeded"):
        middleware.wrap_model_call(
            request,
            lambda scoped_request: ModelResponse(result=[AIMessage(content="ok")]),
        )


def test_token_budget_middleware_applies_user_calendar_month_window(tmp_path):
    store = SQLiteTokenUsageStore(db_path=str(tmp_path / "usage.db"))
    now = datetime.now(timezone.utc)
    previous_month = 12 if now.month == 1 else now.month - 1
    previous_year = now.year - 1 if now.month == 1 else now.year
    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-old",
            total_tokens=10,
            created_at=datetime(previous_year, previous_month, 1, tzinfo=timezone.utc),
        )
    )
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(
            max_user_tokens=10,
            user_token_window={
                "period": "calendar_month",
                "timezone": "UTC",
            },
        ),
        usage_store=store,
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    response = middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(result=[AIMessage(content="ok")]),
    )

    assert response.result[0].content == "ok"

    store.write_usage(
        TokenUsageRecord(
            agent_name="planner",
            model="gpt-test",
            model_provider="openai",
            user_id="user-1",
            context_id="session-1",
            task_id="task-current",
            total_tokens=10,
            created_at=now,
        )
    )

    with pytest.raises(TokenBudgetExceededError, match="User token budget exceeded"):
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


def test_token_budget_middleware_does_not_fail_model_call_when_usage_write_fails():
    middleware = TokenBudgetMiddleware(
        budget=TokenBudgetConfig(),
        usage_store=FailingUsageStore(),
        agent_name="planner",
    )
    request = ModelRequest(
        model=None,
        messages=[HumanMessage(content="hello")],
        runtime=DummyRuntime(),
    )

    response = middleware.wrap_model_call(
        request,
        lambda scoped_request: ModelResponse(
            result=[
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                )
            ]
        ),
    )

    assert response.result[0].content == "ok"
