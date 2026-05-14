from __future__ import annotations

import logging
from typing import Any

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

from automa_ai.config.token_budget import TokenBudgetConfig
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
            summary = self.usage_store.summarize_usage(
                context_id=scope["context_id"],
            )
            if summary.total_tokens >= self.budget.max_session_tokens:
                raise TokenBudgetExceededError(
                    f"Session token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_session_tokens} tokens used."
                )
        if self.budget.max_user_tokens is not None and scope["user_id"]:
            summary = self.usage_store.summarize_usage(user_id=scope["user_id"])
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
            summary = await self.usage_store.asummarize_usage(
                context_id=scope["context_id"],
            )
            if summary.total_tokens >= self.budget.max_session_tokens:
                raise TokenBudgetExceededError(
                    f"Session token budget exceeded: {summary.total_tokens}/"
                    f"{self.budget.max_session_tokens} tokens used."
                )
        if self.budget.max_user_tokens is not None and scope["user_id"]:
            summary = await self.usage_store.asummarize_usage(user_id=scope["user_id"])
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
