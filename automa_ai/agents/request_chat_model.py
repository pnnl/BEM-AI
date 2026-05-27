import json
from collections.abc import Iterator
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _convert_dict_to_message,
    _convert_message_to_dict,
)
from pydantic import Field, SecretStr

from automa_ai.common.normalization import sanitize_model_identifier


class RequestChatCompletionsModel(BaseChatModel):
    model: str
    base_url: str
    api_key: SecretStr
    temperature: float = 0
    timeout: float | None = 60
    max_tokens: int | None = None
    streaming: bool = True
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    default_headers: dict[str, str] = Field(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "request_chat_completions"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "base_url": self.base_url}

    def bind_tools(
        self,
        tools: list[dict[str, Any] | type | BaseTool | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        formatted_tools = [convert_to_openai_tool(tool) for tool in tools]
        bind_kwargs: dict[str, Any] = {"tools": formatted_tools, **kwargs}
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return self.bind(**bind_kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stop=stop, stream=True, **kwargs)
        events = list(self._iter_events(payload))
        return self._build_chat_result(events)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager=None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        payload = self._build_payload(messages, stop=stop, stream=True, **kwargs)
        for event in self._iter_events(payload):
            chunk = self._event_to_chunk(event)
            if chunk is not None:
                yield chunk

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        headers.update(self.default_headers)
        return headers

    def _build_payload(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        stream: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_convert_message_to_dict(message) for message in messages],
            "stream": stream,
            "temperature": self.temperature,
            **self.model_kwargs,
        }
        if stream:
            stream_options = payload.get("stream_options")
            if stream_options is None:
                payload["stream_options"] = {"include_usage": True}
            elif isinstance(stream_options, dict) and "include_usage" not in stream_options:
                payload["stream_options"] = {
                    **stream_options,
                    "include_usage": True,
                }
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if stop:
            payload["stop"] = stop
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value
        return payload

    def _iter_events(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type:
                    yield from self._parse_sse(response.iter_lines())
                    return
                data = response.json()
                if isinstance(data, str):
                    data = json.loads(data)
                yield data

    def _parse_sse(self, lines: Iterator[str]) -> Iterator[dict[str, Any]]:
        for raw_line in lines:
            line = raw_line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            event = json.loads(data)
            if isinstance(event, str):
                event = json.loads(event)
            yield event

    def _event_to_chunk(self, event: dict[str, Any]) -> ChatGenerationChunk | None:
        choices = event.get("choices") or []
        usage_metadata = None
        if event.get("usage"):
            usage_metadata = {
                "input_tokens": event["usage"].get("prompt_tokens", 0),
                "output_tokens": event["usage"].get("completion_tokens", 0),
                "total_tokens": event["usage"].get("total_tokens", 0),
            }

        if not choices:
            if usage_metadata is None:
                return None

            generation_info = {
                "finish_reason": None,
                "model_name": sanitize_model_identifier(event.get("model")),
                "model_provider": self._llm_type,
                "usage": event["usage"],
            }
            chunk_message = AIMessageChunk(content="")
            chunk_message.usage_metadata = usage_metadata
            return ChatGenerationChunk(message=chunk_message, generation_info=generation_info)

        choice = choices[0]
        delta = choice.get("delta")
        if not delta:
            message = choice.get("message") or {}
            content = message.get("content") or message.get("reasoning") or ""
            if not content and not message.get("tool_calls") and usage_metadata is None:
                return None
            chunk_message = AIMessageChunk(
                content=content,
                additional_kwargs={"tool_calls": message.get("tool_calls", [])},
            )
        else:
            delta_payload = {"id": event.get("id"), **delta}
            if (
                not delta_payload.get("content")
                and not delta_payload.get("tool_calls")
                and usage_metadata is None
            ):
                return None
            chunk_message = _convert_delta_to_message_chunk(delta_payload, AIMessageChunk)

        generation_info = {
            "finish_reason": choice.get("finish_reason"),
            "model_name": sanitize_model_identifier(event.get("model")),
            "model_provider": self._llm_type,
        }
        if usage_metadata is not None:
            generation_info["usage"] = event["usage"]
            chunk_message.usage_metadata = usage_metadata
        return ChatGenerationChunk(message=chunk_message, generation_info=generation_info)

    def _build_chat_result(self, events: list[dict[str, Any]]) -> ChatResult:
        if not events:
            raise ValueError("No response events were returned by the request-based chat provider.")

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        last_event = events[-1]

        for event in events:
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            if delta := choice.get("delta"):
                if delta.get("content"):
                    content_parts.append(delta["content"])
                if delta.get("reasoning"):
                    reasoning_parts.append(delta["reasoning"])
                for raw_tool_call in delta.get("tool_calls", []) or []:
                    index = raw_tool_call.get("index", 0)
                    current = tool_calls.setdefault(
                        index,
                        {
                            "id": raw_tool_call.get("id"),
                            "type": raw_tool_call.get("type", "function"),
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if raw_tool_call.get("id"):
                        current["id"] = raw_tool_call["id"]
                    function = raw_tool_call.get("function", {})
                    if function.get("name"):
                        current["function"]["name"] = function["name"]
                    if function.get("arguments"):
                        current["function"]["arguments"] += function["arguments"]
                continue

            message = choice.get("message") or {}
            if message.get("content"):
                content_parts.append(message["content"])
            if message.get("reasoning"):
                reasoning_parts.append(message["reasoning"])
            for index, raw_tool_call in enumerate(message.get("tool_calls", []) or []):
                tool_calls[index] = raw_tool_call

        message_payload: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) or "".join(reasoning_parts),
        }
        if tool_calls:
            message_payload["tool_calls"] = [
                tool_calls[index] for index in sorted(tool_calls)
            ]

        message = _convert_dict_to_message(message_payload)
        if isinstance(message, AIMessage) and last_event.get("usage"):
            usage = last_event["usage"]
            message.usage_metadata = {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        generation_info = {
            "model_name": sanitize_model_identifier(last_event.get("model")),
            "model_provider": self._llm_type,
        }
        finish_reason = None
        if last_event.get("choices"):
            finish_reason = last_event["choices"][0].get("finish_reason")
        if finish_reason:
            generation_info["finish_reason"] = finish_reason

        return ChatResult(
            generations=[
                ChatGeneration(
                    message=message,
                    generation_info=generation_info,
                )
            ],
            llm_output=generation_info,
        )
