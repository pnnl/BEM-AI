import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

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
from automa_ai.hook import ContextPipeline, HookRunner, TurnResult
from automa_ai.telemetry import (
    AutomaLLMCallbackHandler,
    current_span_id,
    current_trace_id,
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


class RecordingAfterTurnHook:
    def __init__(self) -> None:
        self.result = None
        self.error = None

    async def after_turn(self, turn, result):
        self.result = result

    async def on_turn_error(self, turn, error):
        self.error = type(error).__name__


class FailingAfterTurnHook:
    def __init__(self) -> None:
        self.error = None

    async def after_turn(self, turn, result):
        raise RuntimeError("after failed")

    async def on_turn_error(self, turn, error):
        self.error = type(error).__name__


class FailingContextProvider:
    async def collect(self, turn):
        raise RuntimeError("context failed")


def build_agent(
    *,
    retriever=None,
    memory_manager=None,
    telemetry_config=None,
    hook_runner=None,
    context_pipeline=None,
) -> GenericLangGraphChatAgent:
    return GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        retriever=retriever,
        memory_manager=memory_manager,
        telemetry_config=telemetry_config,
        hook_runner=hook_runner,
        context_pipeline=context_pipeline,
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


def test_runnable_config_includes_llm_callback_when_telemetry_enabled():
    agent = build_agent(telemetry_config={"enabled": True, "recorder": "noop"})

    config = agent._build_runnable_config("session-1", "user-1", "task-1")

    assert config["configurable"]["thread_id"] == "test-agent:session-1"
    assert config["metadata"]["session.id"] == "session-1"
    assert config["metadata"]["task.id"] == "task-1"
    assert config["metadata"]["user.id"] == "user-1"
    assert len(config["callbacks"]) == 1
    assert isinstance(config["callbacks"][0], AutomaLLMCallbackHandler)


def test_runnable_config_omits_llm_callback_when_telemetry_disabled():
    agent = build_agent(telemetry_config={"enabled": False})

    config = agent._build_runnable_config("session-1", "user-1", "task-1")

    assert "callbacks" not in config
    assert "metadata" not in config


@pytest.mark.asyncio
async def test_agent_aclose_runs_telemetry_cleanup_once():
    calls: list[str] = []

    class DummyTelemetry:
        enabled = True

        def close(self):
            calls.append("telemetry-close")

        async def aflush(self):
            calls.append("telemetry-aflush")

        async def aclose(self):
            calls.append("telemetry-aclose")

    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        checkpointer_cleanup=lambda: calls.append("checkpointer-close"),
    )
    agent.telemetry = DummyTelemetry()

    await agent.aclose()
    await agent.aclose()
    agent.close()

    assert calls == [
        "checkpointer-close",
        "telemetry-aflush",
        "telemetry-aclose",
    ]


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


def test_subagent_event_format_omits_multimodal_payload_data():
    event = StreamEvent(
        source="subagent:test",
        type="chunk",
        content=[
            {"type": "text", "text": "rendered"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "secret-base64",
                },
            },
        ],
        metadata={"final": True},
    )

    formatted = GenericLangGraphChatAgent._format_subagent_event(event)

    assert formatted.startswith("(final) rendered")
    assert "[image/png attachment omitted from stream]" in formatted
    assert "secret-base64" not in formatted


def test_event_identity_attributes_omit_absent_ids():
    assert GenericLangGraphChatAgent._event_identity_attributes(
        session_id="session-1"
    ) == {"session.id": "session-1"}


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
async def test_invoke_after_turn_receives_common_turn_result():
    class DummyGraph:
        async def ainvoke(self, payload, config):
            return {"messages": [AIMessageChunk(content="invoke output")]}

    hook = RecordingAfterTurnHook()
    agent = build_agent(hook_runner=HookRunner([hook]))
    agent.graph = DummyGraph()

    await agent.invoke("hello", "session-1")

    assert isinstance(hook.result, TurnResult)
    assert hook.result.mode == "invoke"
    assert hook.result.content == "invoke output"
    assert hook.result.raw_response["messages"][0].content == "invoke output"


@pytest.mark.asyncio
async def test_invoke_after_turn_failure_preserves_response():
    class DummyGraph:
        async def ainvoke(self, payload, config):
            return {"ok": True}

    hook = FailingAfterTurnHook()
    agent = build_agent(hook_runner=HookRunner([hook]))
    agent.graph = DummyGraph()

    result = await agent.invoke("hello", "session-1")

    assert result == {"ok": True}
    assert hook.error is None


@pytest.mark.asyncio
async def test_invoke_context_provider_failure_degrades_with_telemetry(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"

    class DummyGraph:
        async def ainvoke(self, payload, config):
            return {"messages": [AIMessageChunk(content="ok")]}

    hook = RecordingAfterTurnHook()
    agent = build_agent(
        hook_runner=HookRunner([hook]),
        context_pipeline=ContextPipeline([FailingContextProvider()]),
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        },
    )
    agent.graph = DummyGraph()

    result = await agent.invoke("hello", "session-1")

    assert result["messages"][0].content == "ok"
    assert hook.result.degraded is True
    assert hook.result.missing_providers == ["FailingContextProvider"]
    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    event = next(
        record for record in records if record.get("name") == "context_provider.failed"
    )
    assert event["attributes"]["context.provider"] == "FailingContextProvider"
    assert event["attributes"]["exception.type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_invoke_records_model_usage_telemetry(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"

    class DummyGraph:
        async def ainvoke(self, payload, config):
            return {
                "messages": [
                    AIMessage(
                        content="ok",
                        usage_metadata={
                            "input_tokens": 11,
                            "output_tokens": 4,
                            "total_tokens": 15,
                        },
                        response_metadata={
                            "model": "gpt-4o",
                            "model_provider": "openai",
                            "finish_reason": "stop",
                        },
                    )
                ]
            }

    agent = build_agent(
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        },
    )
    agent.graph = DummyGraph()

    await agent.invoke("hello", "session-1", task_id="task-1", user_id="user-1")

    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    event = next(record for record in records if record.get("name") == "model.usage")
    assert event["attributes"]["model.name"] == "gpt-4o"
    assert event["attributes"]["model.provider"] == "openai"
    assert event["attributes"]["model.finish_reason"] == "stop"
    assert event["attributes"]["model.usage.input_tokens"] == 11
    assert event["attributes"]["model.usage.output_tokens"] == 4
    assert event["attributes"]["model.usage.total_tokens"] == 15
    assert event["attributes"]["session.id"] == "session-1"
    assert event["attributes"]["task.id"] == "task-1"
    assert event["attributes"]["user.id"] == "user-1"


@pytest.mark.asyncio
async def test_invoke_does_not_run_error_hook_on_cancellation():
    class DummyGraph:
        async def ainvoke(self, payload, config):
            raise asyncio.CancelledError()

    hook = RecordingAfterTurnHook()
    agent = build_agent(hook_runner=HookRunner([hook]))
    agent.graph = DummyGraph()

    with pytest.raises(asyncio.CancelledError):
        await agent.invoke("hello", "session-1")

    assert hook.error is None


@pytest.mark.asyncio
async def test_invoke_records_agent_turn_telemetry(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"
    captured: dict = {}

    class DummyGraph:
        async def ainvoke(self, payload, config):
            captured["payload"] = payload
            captured["config"] = config
            return {"ok": True}

    agent = GenericLangGraphChatAgent(
        agent_name="test-agent",
        description="test",
        instructions="test",
        chat_model=None,
        response_format=None,
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        },
    )
    agent.graph = DummyGraph()

    result = await agent.invoke(
        "hello",
        "session-1",
        task_id="task-1",
        user_id="user-1",
    )

    assert result == {"ok": True}
    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["type"] for record in records] == [
        "span_start",
        "event",
        "event",
        "span_end",
    ]
    assert records[0]["name"] == "agent.turn"
    assert records[0]["attributes"]["agent.name"] == "test-agent"
    assert records[1]["attributes"]["message.content"]["length"] == 5
    assert records[1]["attributes"]["user.id"] == "user-1"
    assert records[2]["attributes"]["user.id"] == "user-1"
    assert records[-1]["status"] == "ok"


@pytest.mark.asyncio
async def test_turn_input_builder_includes_context_and_memory():
    agent = build_agent(retriever=DummyRetriever(), memory_manager=DummyMemoryManager())
    turn_inputs = await agent.turn_input_builder.build_inputs(
        query="hello",
        context_id="session-1",
    )
    inputs = turn_inputs.inputs

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
async def test_forward_subagent_events_sanitizes_metadata_payload(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"
    agent = build_agent(
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        }
    )
    subagent_queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    output_queue: asyncio.Queue = asyncio.Queue()

    task = asyncio.create_task(
        agent._forward_subagent_events(subagent_queue, output_queue)
    )
    await subagent_queue.put(
        StreamEvent(
            source="subagent:test",
            type="text",
            content="hello",
            metadata={"api_key": "secret", "note": "private"},
        )
    )

    await asyncio.wait_for(output_queue.get(), timeout=1)
    task.cancel()
    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]

    metadata_payload = records[0]["attributes"]["subagent.metadata_payload"]
    assert metadata_payload["length"] > 0
    assert metadata_payload["sha256"]
    assert "content" not in metadata_payload


@pytest.mark.asyncio
async def test_stream_cancelled_during_setup_closes_span_as_error(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"
    agent = build_agent(
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
        }
    )

    async def raise_cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    agent.turn_input_builder.build_inputs = raise_cancelled

    with pytest.raises(asyncio.CancelledError):
        async for _ in agent.stream("hello", "session-1", "task-1"):
            pass

    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    assert records[-1]["type"] == "span_end"
    assert records[-1]["status"] == "error"
    assert records[-1]["attributes"]["exception.type"] == "CancelledError"
    assert current_trace_id() is None
    assert current_span_id() is None


@pytest.mark.asyncio
async def test_stream_generator_exit_closes_span_as_ok(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"

    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(content="partial output"), {}
            await asyncio.sleep(10)

    agent = build_agent(
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
        }
    )
    agent.graph = DummyGraph()

    stream = agent.stream("hello", "session-1", "task-1")
    item = await stream.__anext__()
    assert item["content"] == "partial output"
    await stream.aclose()

    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    span_end = [record for record in records if record["type"] == "span_end"][-1]
    assert span_end["status"] == "ok"
    assert "exception.type" not in span_end["attributes"]
    assert any(record.get("name") == "stream.closed" for record in records)
    assert current_trace_id() is None
    assert current_span_id() is None


@pytest.mark.asyncio
async def test_stream_after_turn_receives_compact_final_result():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(content="hello "), {}
            yield AIMessageChunk(content="world"), {}

    hook = RecordingAfterTurnHook()
    agent = build_agent(hook_runner=HookRunner([hook]))
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items[-1]["content"] == "hello world"
    assert isinstance(hook.result, TurnResult)
    assert hook.result.mode == "stream"
    assert hook.result.content == "hello world"
    assert hook.result.artifact_content == ""
    assert hook.result.status == "completed"
    assert hook.result.degraded is False
    assert hook.result.missing_providers == []


@pytest.mark.asyncio
async def test_stream_incomplete_forwarder_skips_after_turn_and_emits_telemetry(
    tmp_path,
):
    telemetry_path = tmp_path / "telemetry.jsonl"

    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            raise asyncio.CancelledError()
            yield

    hook = RecordingAfterTurnHook()
    agent = build_agent(
        hook_runner=HookRunner([hook]),
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        },
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items == []
    assert hook.result is None
    assert hook.error is None
    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(record.get("name") == "stream.incomplete" for record in records)


@pytest.mark.asyncio
async def test_stream_context_provider_failure_marks_turn_result_degraded():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(content="hello"), {}

    hook = RecordingAfterTurnHook()
    agent = build_agent(
        hook_runner=HookRunner([hook]),
        context_pipeline=ContextPipeline([FailingContextProvider()]),
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items[-1]["content"] == "hello"
    assert hook.result.degraded is True
    assert hook.result.missing_providers == ["FailingContextProvider"]


@pytest.mark.asyncio
async def test_stream_after_turn_failure_does_not_emit_error():
    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(content="hello"), {}

    hook = FailingAfterTurnHook()
    agent = build_agent(hook_runner=HookRunner([hook]))
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items[-1]["content"] == "hello"
    assert hook.error is None


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
async def test_stream_records_model_usage_telemetry(tmp_path):
    telemetry_path = tmp_path / "telemetry.jsonl"

    class DummyGraph:
        async def astream(self, inputs, config, stream_mode="messages"):
            yield AIMessageChunk(
                content="hello ",
                usage_metadata={
                    "input_tokens": 7,
                    "output_tokens": 1,
                    "total_tokens": 8,
                },
            ), {}
            yield AIMessageChunk(
                content="world",
                usage_metadata={
                    "input_tokens": 0,
                    "output_tokens": 2,
                    "total_tokens": 2,
                },
                response_metadata={
                    "model": "claude-3-5-sonnet",
                    "model_provider": "anthropic",
                    "stop_reason": "end_turn",
                },
            ), {}

    agent = build_agent(
        telemetry_config={
            "enabled": True,
            "recorder": "jsonl",
            "path": str(telemetry_path),
            "content_mode": "metadata",
        },
    )
    agent.graph = DummyGraph()

    items = [item async for item in agent.stream("hello", "session-1", "task-1")]

    assert items[-1]["content"] == "hello world"
    agent.telemetry.flush()
    records = [
        json.loads(line)
        for line in telemetry_path.read_text(encoding="utf-8").splitlines()
    ]
    event = next(record for record in records if record.get("name") == "model.usage")
    assert event["attributes"]["model.name"] == "claude-3-5-sonnet"
    assert event["attributes"]["model.provider"] == "anthropic"
    assert event["attributes"]["model.finish_reason"] == "end_turn"
    assert event["attributes"]["model.usage.input_tokens"] == 7
    assert event["attributes"]["model.usage.output_tokens"] == 3
    assert event["attributes"]["model.usage.total_tokens"] == 10


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
