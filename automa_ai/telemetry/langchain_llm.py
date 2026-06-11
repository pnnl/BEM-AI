"""LangChain callback handler for AUTOMA LLM-call telemetry."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.messages.ai import add_usage

from automa_ai.telemetry.facade import SpanScope, Telemetry


class AutomaLLMCallbackHandler(AsyncCallbackHandler):
    """Record one AUTOMA span for each LangChain chat/LLM run.

    LangChain callbacks are the least provider-specific place to observe model
    calls: the same handler sees Gemini, OpenAI, Bedrock, and plain LLM runs
    after LangGraph has decided which internal model call to execute.
    """

    def __init__(
        self,
        telemetry: Telemetry,
        *,
        base_attributes: dict[str, Any] | None = None,
    ) -> None:
        self.telemetry = telemetry
        self.base_attributes = dict(base_attributes or {})
        # LangChain reports start/end/error through separate callback methods;
        # keep the open AUTOMA span keyed by LangChain's run_id until the run
        # completes.
        self._spans: dict[UUID, SpanScope] = {}
        self._usage_by_run: dict[UUID, dict[str, Any]] = {}

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Start a GenAI span for chat-model calls with structured messages."""
        attributes = self._start_attributes(
            serialized=serialized,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            invocation_params=kwargs.get("invocation_params"),
        )
        attributes["gen_ai.prompt"] = _messages_json(messages)
        attributes["input.value"] = attributes["gen_ai.prompt"]
        self._start_span(run_id, attributes)

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Start a GenAI span for non-chat LLM calls with string prompts."""
        attributes = self._start_attributes(
            serialized=serialized,
            run_id=run_id,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            invocation_params=kwargs.get("invocation_params"),
        )
        attributes["gen_ai.prompt"] = json.dumps(prompts, default=str)
        attributes["input.value"] = attributes["gen_ai.prompt"]
        self._start_span(run_id, attributes)

    async def on_llm_end(
        self,
        response: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Emit response/usage events while the model span is current, then close it."""
        span = self._spans.pop(run_id, None)
        if span is None:
            return
        try:
            output_attributes = _response_output_attributes(response)
            if output_attributes:
                self.telemetry.event("llm.output", attributes=output_attributes)
            usage_attributes = _response_usage_attributes(
                response,
                accumulated_usage=self._usage_by_run.pop(run_id, None),
            )
            if usage_attributes:
                self.telemetry.event("model.usage", attributes=usage_attributes)
        finally:
            span.__exit__(None, None, None)

    async def on_llm_new_token(
        self,
        token: str,
        *,
        chunk: Any | None = None,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Accumulate token usage reported on streaming chunks."""
        usage = _usage_from_chunk(chunk)
        if usage:
            self._usage_by_run[run_id] = dict(
                add_usage(self._usage_by_run.get(run_id), usage)
            )

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Close the model span with error status if LangChain reports failure."""
        span = self._spans.pop(run_id, None)
        self._usage_by_run.pop(run_id, None)
        if span is None:
            return
        span.__exit__(type(error), error, error.__traceback__)

    def _start_span(self, run_id: UUID, attributes: dict[str, Any]) -> None:
        """Create and enter an AUTOMA span for a LangChain run id."""
        if not self.telemetry.enabled:
            return
        if run_id in self._spans:
            return
        span = self.telemetry.span("llm.call", kind="client", attributes=attributes)
        # SpanScope is normally used as a context manager. LangChain splits a
        # run across callback methods, so the handler manually enters here and
        # exits from on_llm_end/on_llm_error.
        span.__enter__()
        self._spans[run_id] = span

    def _start_attributes(
        self,
        *,
        serialized: dict[str, Any],
        run_id: UUID,
        parent_run_id: UUID | None,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
        invocation_params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build stable start attributes from LangChain's provider-shaped metadata."""
        metadata = dict(metadata or {})
        invocation_params = dict(invocation_params or {})
        model = _first_value(
            invocation_params,
            metadata,
            serialized.get("kwargs") if isinstance(serialized, dict) else {},
            keys=("model", "model_name", "model_id", "ls_model_name"),
        )
        provider = _first_value(
            metadata,
            serialized,
            keys=("ls_provider", "model_provider", "provider"),
        )
        attributes: dict[str, Any] = {
            **self.base_attributes,
            "llm.run_id": str(run_id),
            "gen_ai.operation.name": "chat",
            "gen_ai.output.type": "text",
        }
        if parent_run_id is not None:
            attributes["llm.parent_run_id"] = str(parent_run_id)
        if tags:
            attributes["llm.tags"] = tags
        if model is not None:
            attributes["model.name"] = model
            attributes["gen_ai.request.model"] = model
        if provider is not None:
            attributes["model.provider"] = provider
            attributes["gen_ai.provider.name"] = provider
        else:
            attributes["gen_ai.provider.name"] = "langchain"
        _copy_invocation_params(attributes, invocation_params)
        return attributes


def _copy_invocation_params(
    attributes: dict[str, Any],
    invocation_params: dict[str, Any],
) -> None:
    """Copy supported model parameters into OTEL GenAI request attributes."""
    for key in (
        "temperature",
        "top_p",
        "top_k",
        "max_tokens",
        "frequency_penalty",
        "presence_penalty",
    ):
        value = invocation_params.get(key)
        if value is not None:
            attributes[f"gen_ai.request.{key}"] = value


def _response_output_attributes(response: Any) -> dict[str, Any]:
    """Extract response text, response model, and finish reason from LLMResult."""
    output = _response_text(response)
    attributes: dict[str, Any] = {}
    if output is not None:
        attributes["gen_ai.completion"] = output
        attributes["output.value"] = output
    model = _response_model(response)
    if model is not None:
        attributes["model.response_name"] = model
        attributes["gen_ai.response.model"] = model
    finish_reasons = _finish_reasons(response)
    if finish_reasons:
        attributes["model.finish_reason"] = finish_reasons[0]
        attributes["gen_ai.response.finish_reasons"] = finish_reasons
    return attributes


def _response_usage_attributes(
    response: Any,
    *,
    accumulated_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract provider token usage from LangChain's preferred response locations."""
    usage = _usage_from_messages(response)
    if not usage:
        usage = _usage_from_llm_output(response)
    usage = _prefer_complete_usage(usage, accumulated_usage)
    attributes: dict[str, Any] = {}
    model = _response_model(response)
    provider = _response_provider(response)
    if model is not None:
        attributes["model.name"] = model
    if provider is not None:
        attributes["model.provider"] = provider
    if usage.get("input_tokens") is not None:
        attributes["model.usage.input_tokens"] = usage["input_tokens"]
    if usage.get("output_tokens") is not None:
        attributes["model.usage.output_tokens"] = usage["output_tokens"]
    total_tokens = usage.get("total_tokens")
    if total_tokens is None and (
        usage.get("input_tokens") is not None or usage.get("output_tokens") is not None
    ):
        total_tokens = int(usage.get("input_tokens") or 0) + int(
            usage.get("output_tokens") or 0
        )
    if total_tokens is not None:
        attributes["model.usage.total_tokens"] = total_tokens
    return attributes


def _prefer_complete_usage(
    response_usage: dict[str, Any],
    accumulated_usage: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer accumulated streaming usage when it is more complete than end usage.

    Some streaming providers surface usage incrementally on chunks but leave the
    final LLMResult with only the last tiny usage payload. Avoid allowing that
    final payload to overwrite the accumulated chunk totals.
    """
    if not accumulated_usage:
        return response_usage
    if not response_usage:
        return dict(accumulated_usage)
    accumulated_total = _usage_total(accumulated_usage)
    response_total = _usage_total(response_usage)
    if accumulated_total > response_total:
        return dict(accumulated_usage)
    return response_usage


def _messages_json(messages: list[list[BaseMessage]]) -> str:
    """Serialize LangChain chat batches into a compact role/content JSON payload."""
    return json.dumps(
        [
            [_message_dict(message) for message in message_group]
            for message_group in messages
        ],
        default=str,
        ensure_ascii=False,
        sort_keys=True,
    )


def _message_dict(message: BaseMessage) -> dict[str, Any]:
    """Return the message fields useful for prompt observability."""
    role = getattr(message, "type", None) or message.__class__.__name__
    return {
        "role": role,
        "content": _content_to_text(getattr(message, "content", None)),
    }


def _response_text(response: Any) -> str | None:
    """Flatten all generations in an LLMResult into one displayable response string."""
    texts: list[str] = []
    for generation in _iter_generations(response):
        message = getattr(generation, "message", None)
        if message is not None:
            text = _content_to_text(getattr(message, "content", None))
        else:
            text = _content_to_text(getattr(generation, "text", None))
        if text:
            texts.append(text)
    if not texts:
        return None
    return "\n".join(texts)


def _usage_from_messages(response: Any) -> dict[str, int]:
    """Sum token usage attached to generated messages.

    Chat models commonly attach `usage_metadata` to each generated AI message.
    Keep summing here because multi-candidate responses can contain more than
    one generation.
    """
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    found = False
    for generation in _iter_generations(response):
        message = getattr(generation, "message", None)
        usage = getattr(message, "usage_metadata", None) if message is not None else {}
        if not usage:
            continue
        found = True
        input_tokens = _int_or_zero(
            usage.get("input_tokens") or usage.get("prompt_tokens")
        )
        output_tokens = _int_or_zero(
            usage.get("output_tokens") or usage.get("completion_tokens")
        )
        total_tokens = _int_or_zero(
            usage.get("total_tokens") or input_tokens + output_tokens
        )
        totals["input_tokens"] += input_tokens
        totals["output_tokens"] += output_tokens
        totals["total_tokens"] += total_tokens
    return totals if found else {}


def _usage_from_llm_output(response: Any) -> dict[str, int]:
    """Fallback for providers that only populate LLMResult.llm_output usage."""
    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens")
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    result: dict[str, int] = {}
    if input_tokens is not None:
        result["input_tokens"] = _int_or_zero(input_tokens)
    if output_tokens is not None:
        result["output_tokens"] = _int_or_zero(output_tokens)
    if total_tokens is not None:
        result["total_tokens"] = _int_or_zero(total_tokens)
    return result


def _usage_from_chunk(chunk: Any | None) -> dict[str, Any]:
    """Extract token usage from LangChain streaming callback chunks."""
    if chunk is None:
        return {}
    message = getattr(chunk, "message", None)
    usage = getattr(message, "usage_metadata", None) if message is not None else None
    if not usage:
        usage = getattr(chunk, "usage_metadata", None)
    return dict(usage or {})


def _usage_total(usage: dict[str, Any]) -> int:
    """Return comparable total tokens for two provider usage payloads."""
    total = usage.get("total_tokens")
    if total is not None:
        return _int_or_zero(total)
    return _int_or_zero(usage.get("input_tokens") or usage.get("prompt_tokens")) + (
        _int_or_zero(usage.get("output_tokens") or usage.get("completion_tokens"))
    )


def _response_model(response: Any) -> Any | None:
    """Find the response model from generated messages or LLMResult metadata."""
    for generation in _iter_generations(response):
        message = getattr(generation, "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        model = metadata.get("model_name") or metadata.get("model")
        if model is not None:
            return model
    llm_output = getattr(response, "llm_output", None) or {}
    return llm_output.get("model_name") or llm_output.get("model")


def _response_provider(response: Any) -> Any | None:
    """Find the provider name from generated message metadata when available."""
    for generation in _iter_generations(response):
        message = getattr(generation, "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        provider = metadata.get("model_provider")
        if provider is not None:
            return provider
    return None


def _finish_reasons(response: Any) -> list[str]:
    """Collect finish/stop reasons across all generations."""
    reasons: list[str] = []
    for generation in _iter_generations(response):
        info = getattr(generation, "generation_info", None) or {}
        reason = info.get("finish_reason") or info.get("stop_reason")
        message = getattr(generation, "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        reason = reason or metadata.get("finish_reason") or metadata.get("stop_reason")
        if reason is not None:
            reasons.append(str(reason))
    return reasons


def _iter_generations(response: Any) -> list[Any]:
    """Flatten LangChain's list-of-lists generation shape."""
    generations = getattr(response, "generations", None) or []
    flattened: list[Any] = []
    for generation_group in generations:
        if isinstance(generation_group, list):
            flattened.extend(generation_group)
        else:
            flattened.append(generation_group)
    return flattened


def _content_to_text(value: Any) -> str:
    """Normalize provider-specific message content into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text is not None:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(value)


def _first_value(*mappings: Any, keys: tuple[str, ...]) -> Any | None:
    """Return the first non-null value from a sequence of dict-like objects."""
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        for key in keys:
            value = mapping.get(key)
            if value is not None:
                return value
    return None


def _int_or_zero(value: Any) -> int:
    """Best-effort integer coercion for provider token metadata."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
