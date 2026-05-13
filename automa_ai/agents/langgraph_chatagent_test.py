import asyncio

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage

from automa_ai.agents.langgraph_chatagent import (
    GenericLangGraphChatAgent,
    _should_emit_tool_response,
)
from automa_ai.agents.remote_agent import StreamEvent
from automa_ai.common.message_accumulator import (
    AIMessageAccumulator,
    ARTIFACT_START,
    ARTIFACT_END,
)
from automa_ai.token_management import TokenBudgetExceededError


class DummyRetriever:
    async def asimilarity_search(self, query: str) -> str:
        return "retrieved context"


class DummyMemoryEntry:
    def __init__(self, timestamp: str, content: str) -> None:
        self.timestamp = timestamp
        self.content = content


class DummyMemoryManager:
    async def retrieve_memories(self, *args, **kwargs):
        return [DummyMemoryEntry("2024-01-01", "remember this")]

    async def add_memory(self, *args, **kwargs):
        return None

    async def manage_memory_size(self):
        return None


def build_agent(*, retriever=None, memory_manager=None) -> GenericLangGraphChatAgent:
    return GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        retriever=retriever,
        memory_manager=memory_manager,
    )


def test_agent_uses_injected_checkpointer():
    sentinel = object()
    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        checkpointer=sentinel,
    )

    assert agent.checkpointer is sentinel


def test_agent_close_runs_checkpointer_cleanup_once():
    calls: list[str] = []
    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        checkpointer_cleanup=lambda: calls.append("closed"),
    )

    agent.close()
    agent.close()

    assert calls == ["closed"]


def test_load_skill_tool_response_is_never_streamed():
    assert not _should_emit_tool_response(
        "load_skill",
        "SKILL: openstudio_sdk_model_editor\nSOURCE: /tmp/skill.md\n\nScope...",
    )
    assert not _should_emit_tool_response("load_skill", "Error: missing skill")
    assert not _should_emit_tool_response(
        "load_skill", "SKILL: example\nThis skill explains failure handling."
    )
    assert _should_emit_tool_response("run_python", "normal result")


@pytest.mark.asyncio
async def test_invoke_uses_agent_scoped_checkpoint_thread_id():
    captured: dict = {}

    class DummyGraph:
        async def ainvoke(self, payload, config):
            captured["payload"] = payload
            captured["config"] = config
            return {"ok": True}

    agent = build_agent()
    agent.graph = DummyGraph()

    result = await agent.invoke("hello", "session-1")

    assert result == {"ok": True}
    assert captured["config"] == {
        "configurable": {
            "thread_id": "test-agent:session-1",
            "automa_context_id": "session-1",
        }
    }


@pytest.mark.asyncio
async def test_build_stream_inputs_includes_context_and_memory():
    agent = build_agent(retriever=DummyRetriever(), memory_manager=DummyMemoryManager())
    inputs = await agent._build_stream_inputs("hello", "session-1")

    system_content = inputs["messages"][0]["content"]
    assert "retrieved context" in system_content
    assert "past conversations" in system_content
    assert "2024-01-01: remember this" in system_content


@pytest.mark.asyncio
async def test_forward_subagent_events_emits_text():
    agent = build_agent()
    subagent_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    output_queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        agent._forward_subagent_events(subagent_queue, output_queue)
    )
    event = StreamEvent(
        source="subagent:test", type="text", content="hello", metadata={"final": True}
    )
    await subagent_queue.put(event)

    item = await asyncio.wait_for(output_queue.get(), timeout=1)
    task.cancel()
    assert item["response_type"] == "text"
    assert "(final)" in item["content"]


@pytest.mark.asyncio
async def test_emit_final_output_emits_data_for_json_artifact():
    agent = build_agent()
    output_queue: asyncio.Queue = asyncio.Queue()
    accumulator = AIMessageAccumulator()

    accumulator.add_chunk(
        AIMessageChunk(content=f'{ARTIFACT_START}{{"foo": "bar"}}{ARTIFACT_END}')
    )

    await agent._emit_final_output(output_queue, accumulator, "session-1", "task-1")
    item = await asyncio.wait_for(output_queue.get(), timeout=1)

    assert item["response_type"] == "data"
    assert item["content"] == {"foo": "bar"}


@pytest.mark.asyncio
async def test_emit_final_output_emits_summary_artifact_before_data_artifact():
    agent = build_agent()
    output_queue: asyncio.Queue = asyncio.Queue()
    accumulator = AIMessageAccumulator()

    accumulator.add_chunk(
        AIMessageChunk(
            content=f'Summary text. {ARTIFACT_START}{{"foo": "bar"}}{ARTIFACT_END}'
        )
    )

    await agent._emit_final_output(output_queue, accumulator, "session-1", "task-1")
    data_item = await asyncio.wait_for(output_queue.get(), timeout=1)

    assert data_item["response_type"] == "data"
    assert data_item["is_task_complete"] is True
    assert data_item["content"] == {"foo": "bar"}
    assert data_item["additional_artifacts"] == [
        {
            "response_type": "text",
            "content": "Summary text.",
            "artifact_name": "test-agent-summary",
        }
    ]


@pytest.mark.asyncio
async def test_stream_does_not_emit_artifact_marker_content_as_status_text():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(content=f"Summary {ARTIFACT_START}"), {}
            yield AIMessageChunk(content='{"foo": "bar"}'), {}
            yield AIMessageChunk(content=ARTIFACT_END), {}

    agent = build_agent()
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    status_text = "".join(
        item["content"]
        for item in items
        if not item["is_task_complete"] and item["response_type"] == "text"
    )
    assert status_text == "Summary "
    assert ARTIFACT_START not in status_text
    assert ARTIFACT_END not in status_text
    assert '{"foo": "bar"}' not in status_text
    assert items[-1]["response_type"] == "data"
    assert items[-1]["content"] == {"foo": "bar"}
    assert items[-1]["additional_artifacts"][0]["content"] == "Summary"


@pytest.mark.asyncio
async def test_stream_filters_bedrock_list_artifact_content():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            meta = {"model_provider": "bedrock_converse"}
            yield AIMessageChunk(
                content=[{"type": "text", "text": f"Summary {ARTIFACT_START}"}],
                response_metadata=meta,
            ), {}
            yield AIMessageChunk(
                content=[{"type": "text", "text": '{"foo": "bar"}'}],
                response_metadata=meta,
            ), {}
            yield AIMessageChunk(
                content=[{"type": "text", "text": ARTIFACT_END}],
                response_metadata=meta,
            ), {}

    agent = build_agent()
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    status_text = "".join(
        item["content"]
        for item in items
        if not item["is_task_complete"] and item["response_type"] == "text"
    )
    assert status_text == "Summary "
    assert ARTIFACT_START not in status_text
    assert ARTIFACT_END not in status_text
    assert '{"foo": "bar"}' not in status_text
    assert items[-1]["response_type"] == "data"
    assert items[-1]["content"] == {"foo": "bar"}
    assert items[-1]["additional_artifacts"][0]["content"] == "Summary"


@pytest.mark.asyncio
async def test_stream_returns_budget_message_for_token_budget_errors():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            raise TokenBudgetExceededError("Session token budget exceeded.")
            yield

    agent = build_agent()
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items == [
        {
            "response_type": "text",
            "is_task_complete": True,
            "require_user_input": False,
            "content": "Session token budget exceeded.",
        }
    ]


@pytest.mark.asyncio
async def test_stream_retries_transient_error_before_output():
    class DummyGraph:
        def __init__(self) -> None:
            self.calls = 0

        async def astream(self, inputs, config, stream_mode="messages"):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError(
                    "503 Service Unavailable: model experiencing high demand"
                )
            yield AIMessageChunk(content="retry succeeded"), {}

    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        transient_retry_attempts=1,
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert agent.graph.calls == 2
    assert items[-1]["is_task_complete"] is True
    assert items[-1]["content"] == "retry succeeded"


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_output_has_started():
    class DummyGraph:
        def __init__(self) -> None:
            self.calls = 0

        async def astream(self, inputs, config, stream_mode="messages"):
            self.calls += 1
            yield AIMessageChunk(content="partial output"), {}
            raise RuntimeError(
                "503 Service Unavailable: model experiencing high demand"
            )

    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        transient_retry_attempts=1,
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert agent.graph.calls == 1
    assert items[0]["content"] == "partial output"
    assert items[-1]["is_task_complete"] is True
    assert "internal error" in items[-1]["content"].lower()


@pytest.mark.asyncio
async def test_stream_does_not_retry_after_human_message_is_queued_to_memory():
    class DummyGraph:
        def __init__(self) -> None:
            self.calls = 0

        async def astream(self, inputs, config, stream_mode="messages"):
            self.calls += 1
            yield HumanMessage(content="hello"), {}
            raise RuntimeError(
                "503 Service Unavailable: model experiencing high demand"
            )

    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        memory_manager=DummyMemoryManager(),
        transient_retry_attempts=1,
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert agent.graph.calls == 1
    assert items[-1]["is_task_complete"] is True
    assert "internal error" in items[-1]["content"].lower()
