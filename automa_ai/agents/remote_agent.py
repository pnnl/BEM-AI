from collections.abc import AsyncGenerator, AsyncIterable, Awaitable
from contextvars import ContextVar
from dataclasses import dataclass
from copy import deepcopy
from typing import Any, Callable, Optional

import httpx
import re

from google.protobuf.json_format import MessageToDict, ParseDict

from a2a.client import Client, ClientCallContext, ClientConfig, create_client
from a2a.helpers.proto_helpers import get_message_text, new_text_message
from a2a.types import (
    AgentCard,
    Message,
    Part,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatusUpdateEvent,
)
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from automa_ai.common.base_agent import BaseAgent
from automa_ai.telemetry import current_span_id, current_trace_id

_subagent_context_id: ContextVar[str | None] = ContextVar(
    "subagent_context_id",
    default=None,
)
_subagent_emitter: ContextVar[Callable[[Any], Awaitable[None]] | None] = ContextVar(
    "subagent_emitter",
    default=None,
)


def set_subagent_context_id(context_id: str) -> Any:
    return _subagent_context_id.set(context_id)


def reset_subagent_context_id(token: Any) -> None:
    _subagent_context_id.reset(token)


def get_subagent_context_id() -> str | None:
    return _subagent_context_id.get()


def set_subagent_emitter(emitter: Callable[[Any], Awaitable[None]]) -> Any:
    return _subagent_emitter.set(emitter)


def reset_subagent_emitter(token: Any) -> None:
    _subagent_emitter.reset(token)


def get_subagent_emitter() -> Callable[[Any], Awaitable[None]] | None:
    return _subagent_emitter.get()


def build_subagent_delegation_instruction(subagents) -> str:
    lines = [
        "## AGENT DELEGATION",
        "You can delegate tasks to the following agent tools when appropriate:",
        "",
    ]

    for spec in subagents:
        lines.append(f"- **{spec.tool_name}**: {spec.description}")

    return "\n".join(lines)


def compute_final(chunks: list[str]) -> str:
    for chunk in reversed(chunks):
        if chunk.strip().isdigit():
            return chunk.strip()
    return chunks[-1]


def _part_to_value(part: Part) -> Any:
    if part.HasField("text"):
        return part.text
    if part.HasField("data"):
        return MessageToDict(part.data)
    if part.HasField("url"):
        return part.url
    if part.HasField("raw"):
        return part.raw
    return ""


def _first_part_value(parts: list[Part]) -> Any:
    if not parts:
        return ""
    return _part_to_value(parts[0])


@dataclass
class SubAgentSpec:
    name: str
    description: str
    agent_card: AgentCard | dict[str, Any]
    request_headers: dict[str, str] | None = None

    @property
    def tool_name(self) -> str:
        return re.sub(r"[^a-zA-Z0-9_]", "_", self.name).lower()

    @property
    def resolved_agent_card(self) -> AgentCard:
        if isinstance(self.agent_card, AgentCard):
            return self.agent_card
        return ParseDict(deepcopy(self.agent_card), AgentCard())


@dataclass
class A2AToolResult:
    final: Optional[Any]
    chunks: list[str]
    task_id: str


@dataclass
class StreamEvent:
    source: str
    type: str
    content: str
    metadata: dict | None = None


class A2AToolAdapter:
    def __init__(
        self,
        *,
        subagent,
        emit_event: Callable[[StreamEvent], Awaitable[None]],
    ):
        self.subagent = subagent
        self.emit_event = emit_event

    async def _emit(self, event: StreamEvent) -> None:
        active_emitter = get_subagent_emitter() or self.emit_event
        if active_emitter:
            await active_emitter(event)

    async def run(self, task: str, context_id: str | None = None) -> A2AToolResult:
        a2a_result = await self.subagent.invoke(task, context_id=context_id)
        chunks: list[str] = []

        if isinstance(a2a_result, Message):
            text = get_message_text(a2a_result)
            if text:
                chunks.append(text)
                await self._emit(
                    StreamEvent(
                        source=f"subagent:{self.subagent.agent_name}",
                        type="subagent_chunk",
                        content=text.rstrip() + "\n",
                        metadata=None,
                    )
                )
            final = text
            task_id = a2a_result.task_id
        else:
            for msg in a2a_result.history:
                text = get_message_text(msg)
                if not text:
                    continue
                chunks.append(text)
                await self._emit(
                    StreamEvent(
                        source=f"subagent:{self.subagent.agent_name}",
                        type="subagent_chunk",
                        content=text.rstrip() + "\n",
                        metadata=None,
                    )
                )

            artifact = a2a_result.artifacts[0] if a2a_result.artifacts else None
            final = _first_part_value(list(artifact.parts)) if artifact else ""
            task_id = a2a_result.id

        await self._emit(
            StreamEvent(
                source=f"subagent:{self.subagent.agent_name}",
                type="subagent_chunk",
                content=str(final),
                metadata={"final": True},
            )
        )

        return A2AToolResult(
            final=final,
            chunks=chunks,
            task_id=task_id,
        )

    async def stream(
        self,
        task: str,
        context_id: str | None = None,
    ) -> AsyncIterable[A2AToolResult]:
        chunks: list[str] = []
        async for chunk in self.subagent.stream(task, context_id=context_id):
            if isinstance(chunk, TaskStatusUpdateEvent):
                if chunk.status.state == TaskState.TASK_STATE_COMPLETED:
                    continue
                if chunk.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                    question = get_message_text(chunk.status.message)
                    await self._emit(
                        StreamEvent(
                            source=f"subagent:{self.subagent.agent_name}",
                            type="subagent_chunk",
                            content=question,
                            metadata=None,
                        )
                    )
                    chunks.append(question)
                if chunk.status.state == TaskState.TASK_STATE_WORKING:
                    message = get_message_text(chunk.status.message)
                    await self._emit(
                        StreamEvent(
                            source=f"subagent:{self.subagent.agent_name}",
                            type="subagent_chunk",
                            content=message,
                            metadata=None,
                        )
                    )
                    chunks.append(message)
            if isinstance(chunk, TaskArtifactUpdateEvent):
                final = _first_part_value(list(chunk.artifact.parts))
                await self._emit(
                    StreamEvent(
                        source=f"subagent:{self.subagent.agent_name}",
                        type="subagent_chunk",
                        content=str(final),
                        metadata=None,
                    )
                )
                yield A2AToolResult(
                    final=final,
                    chunks=chunks,
                    task_id=chunk.task_id,
                )


class SubAgentInput(BaseModel):
    task: str = Field(description="Task description to delegate to the sub-agent")


def make_subagent_tool(
    spec: SubAgentSpec,
    emitter: Callable[[StreamEvent], Awaitable[None]] = None,
    blackboard_contract: str | None = None,
):
    subagent = RemoteAgent(
        agent_name=spec.tool_name,
        subagent_card=spec.resolved_agent_card,
        description=spec.description,
        request_headers=spec.request_headers,
    )

    adapter = A2AToolAdapter(subagent=subagent, emit_event=emitter)

    async def _run(task: str) -> dict:
        chunks: list[A2AToolResult] = []
        delegated_task = task
        if blackboard_contract:
            delegated_task = (
                f"{task}\n\n[SHARED SESSION BLACKBOARD CONTRACT]\n"
                f"{blackboard_contract}\n\n"
                "Use blackboard tools for shared state updates."
            )
        agent_card: AgentCard = adapter.subagent.agent_card
        context_id = get_subagent_context_id()
        if agent_card.capabilities.streaming:
            async for chunk in adapter.stream(delegated_task, context_id=context_id):
                chunks.append(chunk)
        else:
            result = await adapter.run(delegated_task, context_id=context_id)
            chunks.append(result)

        result = chunks[-1] if chunks else None

        if result:
            return {
                "final": result.final,
                "chunks": result.chunks,
                "task_id": result.task_id,
            }
        return {
            "final": (
                "No result produced by the subagent " f"{adapter.subagent.agent_name}"
            ),
            "chunks": "",
            "task_id": "",
        }

    return StructuredTool.from_function(
        name=spec.tool_name,
        description=spec.description,
        coroutine=_run,
        args_schema=SubAgentInput,
    )


class RemoteAgent(BaseAgent):
    """An interface to stream connections to a hands off agent."""

    def __init__(
        self,
        agent_name: str,
        subagent_card: AgentCard,
        description: str,
        request_headers: dict[str, str] | None = None,
    ):
        super().__init__(
            agent_name=agent_name,
            description=description,
            content_types=["text", "text/plain"],
        )

        self._httpx_client = httpx.AsyncClient(timeout=httpx.Timeout(None))
        self._request_headers = dict(request_headers or {})
        self.agent_card = subagent_card
        self._streaming_client: Client | None = None
        self._non_streaming_client: Client | None = None

    async def _get_client(self, *, streaming: bool) -> Client:
        if streaming and self._streaming_client is None:
            self._streaming_client = await create_client(
                self.agent_card,
                client_config=ClientConfig(
                    httpx_client=self._httpx_client,
                    streaming=True,
                ),
            )
        if not streaming and self._non_streaming_client is None:
            self._non_streaming_client = await create_client(
                self.agent_card,
                client_config=ClientConfig(
                    httpx_client=self._httpx_client,
                    streaming=False,
                ),
            )
        return self._streaming_client if streaming else self._non_streaming_client

    def _request_context(self) -> ClientCallContext | None:
        """Expose subagent credentials through the A2A client transport API."""
        if not self._request_headers:
            return None
        return ClientCallContext(service_parameters=dict(self._request_headers))

    def _build_request(
        self,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SendMessageRequest:
        message_metadata = dict(metadata or {})
        if user_id is not None:
            message_metadata.setdefault("user_id", user_id)
        # A2A metadata is the cross-process boundary for subagent calls. Carry
        # only trace identifiers here; message/tool payloads stay in events and
        # are sanitized by the recorder.
        trace_id = current_trace_id()
        span_id = current_span_id()
        if trace_id is not None:
            message_metadata.setdefault("telemetry_trace_id", trace_id)
        if span_id is not None:
            message_metadata.setdefault("telemetry_parent_span_id", span_id)

        a2a_message = new_text_message(
            text=message,
            context_id=context_id,
            task_id=task_id,
            role=Role.ROLE_USER,
        )
        if message_metadata:
            a2a_message.metadata.update(message_metadata)

        return SendMessageRequest(message=a2a_message)

    @staticmethod
    def _unwrap_response(
        response: StreamResponse,
    ) -> Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None:
        if response.HasField("status_update"):
            return response.status_update
        if response.HasField("artifact_update"):
            return response.artifact_update
        if response.HasField("task"):
            return response.task
        if response.HasField("message"):
            return response.message
        return None

    async def invoke(
        self,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task | Message:
        request = self._build_request(
            message,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
        )

        client = await self._get_client(streaming=False)

        last_response: Message | Task | None = None
        async for chunk in client.send_message(
            request,
            context=self._request_context(),
        ):
            event = self._unwrap_response(chunk)
            if isinstance(event, (Message, Task)):
                last_response = event

        if last_response is None:
            raise RuntimeError(
                f"Subagent {self.agent_name} returned no terminal response."
            )
        return last_response

    async def stream(
        self,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncGenerator[
        Message | Task | TaskStatusUpdateEvent | TaskArtifactUpdateEvent,
        None,
    ]:
        request = self._build_request(
            message,
            context_id=context_id,
            task_id=task_id,
            user_id=user_id,
            metadata=metadata,
        )

        client = await self._get_client(streaming=True)

        async for chunk in client.send_message(
            request,
            context=self._request_context(),
        ):
            event = self._unwrap_response(chunk)
            if event is not None:
                yield event

    async def close(self):
        if self._streaming_client is not None:
            await self._streaming_client.close()
        if self._non_streaming_client is not None:
            await self._non_streaming_client.close()
        await self._httpx_client.aclose()
