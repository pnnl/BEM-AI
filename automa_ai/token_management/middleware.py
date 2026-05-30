from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.messages.utils import (
    count_tokens_approximately,
    trim_messages,
)
from langgraph.config import get_config

from automa_ai.config.token_budget import TokenBudgetConfig, TokenBudgetWindowConfig
from automa_ai.token_management.store import TokenUsageRecord, TokenUsageStore

logger = logging.getLogger(__name__)


class TokenBudgetExceededError(RuntimeError):
    """Raised when a user or session token budget is exhausted."""


class TokenBudgetMiddleware(AgentMiddleware):
    """Enforce token budgets at the LangChain model-call boundary.

    This middleware intentionally separates soft prompt overflow from hard
    budget exhaustion. Prompt overflow is handled by trimming the message list
    before the model call. Exhausted user/session budgets raise
    `TokenBudgetExceededError`, which the agent layer can convert to a
    user-facing response.
    """

    def __init__(
        self,
        *,
        budget: TokenBudgetConfig,
        usage_store: TokenUsageStore | None = None,
        agent_name: str | None = None,
    ) -> None:
        self.budget = budget
        self.usage_store = usage_store
        self.agent_name = agent_name

    def wrap_model_call(self, request: ModelRequest, handler):
        """Apply sync budget checks around one model call."""
        scoped = self._apply_prompt_budget(request)
        self._assert_budget_available(scoped)
        response = handler(scoped)
        self._record_response_usage(scoped, response)
        return response

    async def awrap_model_call(self, request: ModelRequest, handler):
        """Apply async budget checks around one model call."""
        scoped = self._apply_prompt_budget(request)
        await self._aassert_budget_available(scoped)
        response = await handler(scoped)
        await self._arecord_response_usage(scoped, response)
        return response

    def _apply_prompt_budget(self, request: ModelRequest) -> ModelRequest:
        """Return a request whose messages fit the configured input budget.

        LangChain's `ModelRequest.messages` excludes the system prompt, so this
        method counts the system prompt separately and trims only conversation
        messages. Trimming is quiet by design because it is the normal way to
        keep long-running agent loops inside a context window.
        """
        request = self._apply_output_budget(request)
        if self.budget.max_input_tokens is None:
            return request

        system_tokens = 0
        if request.system_message is not None:
            system_tokens = count_tokens_approximately([request.system_message])
        message_budget = (
            self.budget.max_input_tokens
            - self.budget.reserve_output_tokens
            - system_tokens
        )
        if message_budget <= 0:
            raise TokenBudgetExceededError(
                "The configured token budget is too small for the system prompt."
            )

        trimmed = trim_messages(
            request.messages,
            max_tokens=message_budget,
            token_counter=count_tokens_approximately,
            strategy=self.budget.trim_strategy,
            allow_partial=self.budget.allow_partial,
            include_system=False,
        )
        return request.override(messages=trimmed)

    def _apply_output_budget(self, request: ModelRequest) -> ModelRequest:
        """Attach a provider output-token cap without overriding caller settings."""
        if self.budget.max_output_tokens is None:
            return request
        settings = dict(request.model_settings or {})
        settings.setdefault(
            self.budget.output_token_limit_key,
            self.budget.max_output_tokens,
        )
        return request.override(model_settings=settings)

    def _assert_budget_available(self, request: ModelRequest) -> None:
        """Raise when the persisted sync usage ledger has exhausted a budget."""
        if self.usage_store is None:
            return
        scope = self._scope_from_request(request)
        if self.budget.max_session_tokens is not None and scope["context_id"]:
            start_time, end_time = self._usage_window(self.budget.session_token_window)
            kwargs = self._summary_kwargs(
                context_id=scope["context_id"],
                start_time=start_time,
                end_time=end_time,
            )
            summary = self.usage_store.summarize_usage(**kwargs)
            if summary.total_tokens >= self.budget.max_session_tokens:
                raise TokenBudgetExceededError(
                    f"Session token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_session_tokens} tokens used."
                )
        if self.budget.max_user_tokens is not None and scope["user_id"]:
            start_time, end_time = self._usage_window(self.budget.user_token_window)
            kwargs = self._summary_kwargs(
                user_id=scope["user_id"],
                start_time=start_time,
                end_time=end_time,
            )
            summary = self.usage_store.summarize_usage(**kwargs)
            if summary.total_tokens >= self.budget.max_user_tokens:
                raise TokenBudgetExceededError(
                    f"User token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_user_tokens} tokens used."
                )

    async def _aassert_budget_available(self, request: ModelRequest) -> None:
        """Raise when the persisted async usage ledger has exhausted a budget."""
        if self.usage_store is None:
            return
        scope = self._scope_from_request(request)
        if self.budget.max_session_tokens is not None and scope["context_id"]:
            start_time, end_time = self._usage_window(self.budget.session_token_window)
            kwargs = self._summary_kwargs(
                context_id=scope["context_id"],
                start_time=start_time,
                end_time=end_time,
            )
            summary = await self.usage_store.asummarize_usage(**kwargs)
            if summary.total_tokens >= self.budget.max_session_tokens:
                raise TokenBudgetExceededError(
                    f"Session token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_session_tokens} tokens used."
                )
        if self.budget.max_user_tokens is not None and scope["user_id"]:
            start_time, end_time = self._usage_window(self.budget.user_token_window)
            kwargs = self._summary_kwargs(
                user_id=scope["user_id"],
                start_time=start_time,
                end_time=end_time,
            )
            summary = await self.usage_store.asummarize_usage(**kwargs)
            if summary.total_tokens >= self.budget.max_user_tokens:
                raise TokenBudgetExceededError(
                    f"User token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_user_tokens} tokens used."
                )

    def _record_response_usage(self, request: ModelRequest, response: Any) -> None:
        """Persist sync usage metadata on a best-effort basis."""
        if self.usage_store is None:
            return
        record = self._record_from_response(request, response)
        if record is not None:
            try:
                self.usage_store.write_usage(record)
            except Exception:
                logger.exception(
                    "Failed to persist token usage for agent %s.",
                    self.agent_name,
                )

    async def _arecord_response_usage(
        self, request: ModelRequest, response: Any
    ) -> None:
        """Persist async usage metadata on a best-effort basis."""
        if self.usage_store is None:
            return
        record = self._record_from_response(request, response)
        if record is not None:
            try:
                await self.usage_store.awrite_usage(record)
            except Exception:
                logger.exception(
                    "Failed to persist token usage for agent %s.",
                    self.agent_name,
                )

    def _record_from_response(
        self,
        request: ModelRequest,
        response: Any,
    ) -> TokenUsageRecord | None:
        """Convert provider usage metadata into a durable usage record.

        Providers differ in when they attach usage metadata during streaming.
        This method only writes records when LangChain has a final message with
        non-zero usage metadata; otherwise it returns `None`.
        """
        messages = self._response_messages(response)
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        model = None
        provider = None
        for message in messages:
            usage = getattr(message, "usage_metadata", None) or {}
            metadata = getattr(message, "response_metadata", None) or {}
            model = model or metadata.get("model") or metadata.get("model_name")
            provider = provider or metadata.get("model_provider")
            totals["input_tokens"] += int(usage.get("input_tokens") or 0)
            totals["output_tokens"] += int(usage.get("output_tokens") or 0)
            totals["total_tokens"] += int(
                usage.get("total_tokens")
                or (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
            )

        if totals["total_tokens"] == 0:
            return None

        scope = self._scope_from_request(request)
        return TokenUsageRecord(
            agent_name=self.agent_name,
            model=model,
            model_provider=provider,
            user_id=scope["user_id"],
            context_id=scope["context_id"],
            task_id=scope["task_id"],
            input_tokens=totals["input_tokens"],
            output_tokens=totals["output_tokens"],
            total_tokens=totals["total_tokens"],
        )

    @staticmethod
    def _response_messages(response: Any) -> list[BaseMessage]:
        """Normalize supported middleware response shapes into messages."""
        if isinstance(response, ModelResponse):
            return list(response.result)
        if isinstance(response, AIMessage):
            return [response]
        result = getattr(response, "result", None)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, BaseMessage)]
        return []

    @staticmethod
    def _scope_from_request(request: ModelRequest) -> dict[str, str | None]:
        """Extract AUTOMA user/session/task identifiers from LangGraph config."""
        config = TokenBudgetMiddleware._config_from_request(request)
        configurable = (
            config.get("configurable", {}) if isinstance(config, dict) else {}
        )
        context_id = configurable.get("automa_context_id")
        if context_id is None:
            thread_id = configurable.get("thread_id")
            if isinstance(thread_id, str) and ":" in thread_id:
                context_id = thread_id.split(":", 1)[1]
            else:
                context_id = thread_id

        return {
            "user_id": configurable.get("actor_id"),
            "context_id": context_id,
            "task_id": configurable.get("task_id"),
        }

    @staticmethod
    def _summary_kwargs(
        *,
        user_id: str | None = None,
        context_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if user_id is not None:
            kwargs["user_id"] = user_id
        if context_id is not None:
            kwargs["context_id"] = context_id
        if start_time is not None:
            kwargs["start_time"] = start_time
        if end_time is not None:
            kwargs["end_time"] = end_time
        return kwargs

    @staticmethod
    def _usage_window(
        window: TokenBudgetWindowConfig | None,
    ) -> tuple[datetime | None, datetime | None]:
        """Return UTC window boundaries for persisted budget checks."""
        if window is None or window.period == "lifetime":
            return None, None

        try:
            tz = ZoneInfo(window.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"Unknown token budget timezone: {window.timezone!r}. "
                "Use an IANA timezone name such as 'UTC', 'America/Los_Angeles', or 'Europe/London'."
            ) from exc

        now = datetime.now(tz)
        if window.period == "rolling":
            if window.rolling_seconds is None or window.rolling_seconds <= 0:
                raise ValueError(
                    "rolling_seconds must be greater than 0 for rolling token windows"
                )
            end_time = now
            start_time = now - timedelta(seconds=window.rolling_seconds)
        elif window.period == "calendar_day":
            start_date = now.date()
            end_date = start_date + timedelta(days=1)
            start_time = datetime.combine(start_date, time.min, tzinfo=tz)
            end_time = datetime.combine(end_date, time.min, tzinfo=tz)
        elif window.period == "calendar_month":
            start_date = now.date().replace(day=1)
            if start_date.month == 12:
                end_date = start_date.replace(year=start_date.year + 1, month=1)
            else:
                end_date = start_date.replace(month=start_date.month + 1)
            start_time = datetime.combine(start_date, time.min, tzinfo=tz)
            end_time = datetime.combine(end_date, time.min, tzinfo=tz)
        else:
            raise ValueError(f"Unsupported token budget window period: {window.period}")

        return start_time.astimezone(timezone.utc), end_time.astimezone(timezone.utc)

    @staticmethod
    def _config_from_request(request: ModelRequest) -> dict[str, Any]:
        """Return the active LangGraph runnable config for real and test runs.

        `Runtime` does not expose `config` in current LangGraph versions. The
        supported runtime path is `get_config()`. Tests may still attach a
        minimal fake `runtime.config`, so this method accepts both forms.
        """
        runtime = getattr(request, "runtime", None)
        config = getattr(runtime, "config", None)
        if isinstance(config, dict):
            return config
        try:
            return get_config()
        except RuntimeError:
            return {}


def build_token_budget_middlewares(
    *,
    budget: TokenBudgetConfig | None,
    usage_store: TokenUsageStore | None,
    model: Any,
    agent_name: str,
) -> list[AgentMiddleware]:
    """Build the middleware stack used by AUTOMA LangGraph chat agents."""
    if budget is None or not budget.enabled:
        return []

    middlewares: list[AgentMiddleware] = [
        TokenBudgetMiddleware(
            budget=budget,
            usage_store=usage_store,
            agent_name=agent_name,
        )
    ]
    if budget.summarize_when_tokens is not None:
        middlewares.append(
            SummarizationMiddleware(
                model,
                trigger=("tokens", budget.summarize_when_tokens),
                keep=("messages", budget.keep_recent_messages),
                token_counter=count_tokens_approximately,
            )
        )
    if budget.max_model_calls_per_turn is not None:
        middlewares.append(
            ModelCallLimitMiddleware(run_limit=budget.max_model_calls_per_turn)
        )
    if budget.max_tool_calls_per_turn is not None:
        middlewares.append(
            ToolCallLimitMiddleware(run_limit=budget.max_tool_calls_per_turn)
        )
    return middlewares
