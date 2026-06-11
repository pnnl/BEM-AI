from __future__ import annotations

import json
import asyncio
import contextvars
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, LLMResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry import (
    AutomaLLMCallbackHandler,
    Telemetry,
    build_telemetry,
    current_span_id,
    current_trace_id,
    list_telemetry_recorders,
    register_telemetry_recorder,
    wrap_langchain_tool,
)
from automa_ai.telemetry import otel as otel_module
from automa_ai.telemetry import otel_encoder
from automa_ai.telemetry import registry as telemetry_registry
from automa_ai.telemetry.recorders import JsonlRecorder
from automa_ai.telemetry.records import (
    EventRecord,
    SpanKind,
    SpanStartRecord,
    parse_telemetry_record,
)

otel_exporter = pytest.importorskip(
    "opentelemetry.sdk.trace.export.in_memory_span_exporter"
)
otel_trace = pytest.importorskip("opentelemetry.trace")
InMemorySpanExporter = otel_exporter.InMemorySpanExporter


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture(autouse=True)
def restore_telemetry_registry_state(monkeypatch):
    with telemetry_registry.TELEMETRY_RECORDER_REGISTRY._lock:
        factories = dict(telemetry_registry.TELEMETRY_RECORDER_REGISTRY._factories)
    plugins_loaded = telemetry_registry._PLUGINS_LOADED
    yield
    with telemetry_registry.TELEMETRY_RECORDER_REGISTRY._lock:
        telemetry_registry.TELEMETRY_RECORDER_REGISTRY._factories = factories
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", plugins_loaded)


def test_jsonl_recorder_writes_span_and_event(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "jsonl",
            "path": str(path),
            "content_mode": "metadata",
            "service_name": "test-service",
        }
    )

    with telemetry.span("agent.turn", attributes={"agent.name": "demo"}):
        telemetry.event("message", attributes={"content": "hello"})

    telemetry.flush()
    records = _read_jsonl(path)
    assert [record["type"] for record in records] == [
        "span_start",
        "event",
        "span_end",
    ]
    assert records[0]["name"] == "agent.turn"
    assert records[1]["attributes"]["content"]["length"] == 5
    assert "content" not in records[1]["attributes"]["content"]
    assert records[0]["attributes"]["agent.name"] == "demo"
    assert records[2]["status"] == "ok"
    assert records[0]["trace_id"] == records[1]["trace_id"] == records[2]["trace_id"]


def test_nested_spans_preserve_parent_child_relationship(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(path)}
    )

    with telemetry.span("agent.turn"):
        parent_span_id = current_span_id()
        trace_id = current_trace_id()
        with telemetry.span("tool.call"):
            assert current_trace_id() == trace_id

    telemetry.flush()
    records = _read_jsonl(path)
    child_start = records[1]
    assert child_start["name"] == "tool.call"
    assert child_start["parent_span_id"] == parent_span_id
    assert len(records[0]["trace_id"]) == 32
    assert len(records[0]["span_id"]) == 16
    assert len(child_start["span_id"]) == 16


def test_span_exit_tolerates_different_context_cleanup(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(path)}
    )

    def enter_span():
        scope = telemetry.span("agent.turn")
        scope.__enter__()
        return scope

    entered_context = contextvars.Context()
    scope = entered_context.run(enter_span)
    exc = GeneratorExit()

    scope.__exit__(GeneratorExit, exc, exc.__traceback__)
    scope.__exit__(None, None, None)

    telemetry.flush()
    records = _read_jsonl(path)
    assert [record["type"] for record in records] == ["span_start", "span_end"]
    assert records[-1]["status"] == "error"
    assert records[-1]["attributes"]["exception.type"] == "GeneratorExit"
    assert current_trace_id() is None
    assert current_span_id() is None


def test_redacted_mode_redacts_secret_values(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "jsonl",
            "path": str(path),
            "content_mode": "redacted",
        }
    )

    with telemetry.span(
        "tool.call",
        attributes={
            "api_key": "secret",
            "payload": "Authorization: Bearer abcdefghijklmnop",
        },
    ):
        pass

    telemetry.flush()
    record = _read_jsonl(path)[0]
    assert record["attributes"]["api_key"] == "[REDACTED]"
    assert "[REDACTED]" in record["attributes"]["payload"]["content"]


def test_token_usage_counts_are_not_redacted(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "jsonl",
            "path": str(path),
            "content_mode": "metadata",
        }
    )

    telemetry.event(
        "model.usage",
        attributes={
            "model.usage.input_tokens": 11,
            "model.usage.output_tokens": 4,
            "auth.token": "secret",
        },
    )

    telemetry.flush()
    record = _read_jsonl(path)[0]
    assert record["attributes"]["model.usage.input_tokens"] == 11
    assert record["attributes"]["model.usage.output_tokens"] == 4
    assert record["attributes"]["auth.token"] == "[REDACTED]"


def test_noop_recorder_does_not_create_path(tmp_path) -> None:
    path = tmp_path / "missing.jsonl"
    telemetry = build_telemetry(
        {"enabled": False, "recorder": "jsonl", "path": str(path)}
    )

    with telemetry.span("agent.turn"):
        telemetry.event("message")

    assert not path.exists()


def test_jsonl_recorder_close_drops_late_records_without_hanging(
    tmp_path, caplog
) -> None:
    recorder = JsonlRecorder(tmp_path / "telemetry.jsonl")
    recorder.record({"type": "event", "name": "before-close"})
    errors: list[BaseException] = []

    def close_recorder() -> None:
        try:
            recorder.close()
        except BaseException as exc:
            errors.append(exc)

    closer = threading.Thread(target=close_recorder)
    closer.start()
    closer.join(timeout=2)

    assert not closer.is_alive()
    assert errors == []
    recorder.record({"type": "event", "name": "after-close"})
    assert "JSONL recorder is closed" in caplog.text


def test_custom_recorder_registry_builds_registered_recorder(tmp_path) -> None:
    class CapturingRecorder:
        def __init__(self) -> None:
            self.items = []
            self.flushed = False
            self.closed = False

        def record(self, item):
            self.items.append(item)

        def flush(self):
            self.flushed = True

        def close(self):
            self.closed = True

    captured: dict[str, object] = {}

    def build_custom_recorder(config, base_attributes, base_dir):
        assert config.options == {"target": "agentcore"}
        assert base_attributes == {"project.id": "demo"}
        assert base_dir == tmp_path
        recorder = CapturingRecorder()
        captured["recorder"] = recorder
        return recorder

    register_telemetry_recorder(
        "test_custom_agentcore",
        build_custom_recorder,
        override=True,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "test_custom_agentcore",
            "options": {"target": "agentcore"},
        },
        base_attributes={"project.id": "demo"},
        base_dir=tmp_path,
    )

    with telemetry.span("agent.turn", attributes={"agent.name": "demo"}):
        telemetry.event("message", attributes={"content": "hello"})

    telemetry.flush()
    telemetry.close()

    recorder = captured["recorder"]
    assert recorder.flushed is True
    assert recorder.closed is True
    assert [item["type"] for item in recorder.items] == [
        "span_start",
        "event",
        "span_end",
    ]
    assert "test_custom_agentcore" in list_telemetry_recorders()


def test_parse_telemetry_record_models_distinct_shapes_leniently() -> None:
    start = parse_telemetry_record(
        {
            "type": "span_start",
            "trace_id": "trace",
            "span_id": "span",
            "parent_span_id": "parent",
            "name": "agent.turn",
            "kind": "unexpected-kind",
            "timestamp": "2026-01-01T00:00:00.000000000Z",
            "attributes": {"agent.name": "demo"},
        }
    )
    event = parse_telemetry_record(
        {
            "type": "event",
            "trace_id": "trace",
            "span_id": None,
            "name": "message",
            "timestamp": "2026-01-01T00:00:00.000000000Z",
            "attributes": {"content": "hello"},
            "kind": "ignored",
        }
    )

    assert isinstance(start, SpanStartRecord)
    assert start.kind is SpanKind.INTERNAL
    assert start.parent_span_id == "parent"
    assert isinstance(event, EventRecord)
    assert event.span_id is None
    assert not hasattr(event, "kind")
    assert parse_telemetry_record({"type": "future_record"}) is None
    assert parse_telemetry_record(None) is None


def test_otel_recorder_exports_spans_events_and_status(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "service_name": "test-service",
            "environment": "test",
            "options": {"processor": "simple"},
        }
    )

    with pytest.raises(RuntimeError):
        with telemetry.span("agent.turn", kind="server"):
            telemetry.event(
                "message",
                attributes={
                    "message.role": "user",
                    "message.content": "hello",
                },
            )
            telemetry.event(
                "model.usage",
                attributes={
                    "model.name": "gpt-4o",
                    "model.provider": "openai",
                    "model.usage.input_tokens": 11,
                    "model.usage.output_tokens": 4,
                    "model.usage.total_tokens": 15,
                },
            )
            with telemetry.span("tool.call", attributes={"tool.name": "demo_tool"}):
                telemetry.event(
                    "tool.input",
                    attributes={
                        "tool.name": "demo_tool",
                        "tool.arguments": {"query": "hvac"},
                    },
                )
                telemetry.event(
                    "tool.output",
                    attributes={
                        "tool.name": "demo_tool",
                        "tool.result": {"ok": True},
                    },
                )
                raise RuntimeError("tool failed")

    telemetry.flush()
    spans = exporter.get_finished_spans()
    by_name = {span.name: span for span in spans}

    assert set(by_name) == {"invoke_agent", "execute_tool demo_tool"}
    agent_span = by_name["invoke_agent"]
    tool_span = by_name["execute_tool demo_tool"]
    assert agent_span.kind.name == "SERVER"
    assert tool_span.parent.span_id == agent_span.context.span_id
    assert tool_span.status.status_code.name == "ERROR"
    assert tool_span.attributes["tool.name"] == "demo_tool"
    assert tool_span.attributes["gen_ai.operation.name"] == "execute_tool"
    assert tool_span.attributes["gen_ai.tool.name"] == "demo_tool"
    assert agent_span.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert agent_span.attributes["gen_ai.provider.name"] == "openai"
    assert (
        agent_span.attributes["automa.span_id"] == f"{agent_span.context.span_id:016x}"
    )
    assert (
        agent_span.attributes["automa.trace_id"]
        == f"{agent_span.context.trace_id:032x}"
    )
    assert agent_span.events[0].name == "message"
    assert agent_span.events[0].attributes["message.role"] == "user"
    assert agent_span.events[0].attributes["message.content"] == (
        '{"length": 5, "sha256": '
        '"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e730'
        '43362938b9824"}'
    )
    assert agent_span.attributes["input.value"] == agent_span.events[0].attributes[
        "message.content"
    ]
    assert agent_span.attributes["gen_ai.prompt"] == agent_span.events[0].attributes[
        "message.content"
    ]
    assert agent_span.events[1].name == "model.usage"
    assert agent_span.events[1].attributes["gen_ai.request.model"] == "gpt-4o"
    assert agent_span.events[1].attributes["gen_ai.provider.name"] == "openai"
    assert agent_span.events[1].attributes["gen_ai.usage.input_tokens"] == 11
    assert agent_span.events[1].attributes["gen_ai.usage.prompt_tokens"] == 11
    assert agent_span.events[1].attributes["gen_ai.usage.output_tokens"] == 4
    assert agent_span.events[1].attributes["gen_ai.usage.completion_tokens"] == 4
    assert agent_span.events[1].attributes["gen_ai.usage.total_tokens"] == 15
    assert agent_span.events[1].attributes["model.usage.total_tokens"] == 15
    assert agent_span.attributes["gen_ai.usage.input_tokens"] == 11
    assert agent_span.attributes["gen_ai.usage.prompt_tokens"] == 11
    assert agent_span.attributes["gen_ai.usage.output_tokens"] == 4
    assert agent_span.attributes["gen_ai.usage.completion_tokens"] == 4
    assert agent_span.attributes["gen_ai.usage.total_tokens"] == 15
    assert tool_span.events[0].name == "tool.input"
    assert tool_span.events[1].name == "tool.output"
    assert tool_span.attributes["input.value"] == tool_span.events[0].attributes[
        "tool.arguments"
    ]
    assert tool_span.attributes["output.value"] == tool_span.events[1].attributes[
        "tool.result"
    ]
    assert agent_span.resource.attributes["service.name"] == "test-service"


@pytest.mark.asyncio
async def test_llm_callback_exports_child_generation_span(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "service_name": "test-service",
            "environment": "test",
            "content_mode": "redacted",
            "options": {"processor": "simple"},
        }
    )
    callback = AutomaLLMCallbackHandler(
        telemetry,
        base_attributes={
            "agent.name": "demo",
            "session.id": "session-1",
            "task.id": "task-1",
            "user.id": "user-1",
        },
    )
    run_id = uuid4()

    with telemetry.span("agent.turn", kind="server", attributes={"agent.name": "demo"}):
        await callback.on_chat_model_start(
            {"kwargs": {"model": "gemini-pro"}},
            [[HumanMessage(content="hello")]],
            run_id=run_id,
            metadata={"ls_provider": "google_genai", "ls_model_name": "gemini-pro"},
            invocation_params={"temperature": 0, "max_tokens": 128},
        )
        await callback.on_llm_new_token(
            "worl",
            chunk=ChatGenerationChunk(
                message=AIMessageChunk(
                    content="worl",
                    usage_metadata={
                        "input_tokens": 11,
                        "output_tokens": 3,
                        "total_tokens": 14,
                    },
                )
            ),
            run_id=run_id,
        )
        await callback.on_llm_new_token(
            "d",
            chunk=ChatGenerationChunk(
                message=AIMessageChunk(
                    content="d",
                    usage_metadata={
                        "input_tokens": 0,
                        "output_tokens": 1,
                        "total_tokens": 1,
                    },
                )
            ),
            run_id=run_id,
        )
        await callback.on_llm_end(
            LLMResult(
                generations=[
                    [
                        ChatGeneration(
                            message=AIMessage(
                                content="world",
                                usage_metadata={
                                    "input_tokens": 0,
                                    "output_tokens": 1,
                                    "total_tokens": 1,
                                },
                                response_metadata={
                                    "model_name": "gemini-pro",
                                    "finish_reason": "stop",
                                    "model_provider": "google_genai",
                                },
                            )
                        )
                    ]
                ],
                llm_output={"model_name": "gemini-pro"},
            ),
            run_id=run_id,
        )

    telemetry.flush()
    by_name = {span.name: span for span in exporter.get_finished_spans()}
    agent_span = by_name["invoke_agent demo"]
    llm_span = by_name["chat gemini-pro"]

    assert llm_span.parent.span_id == agent_span.context.span_id
    assert llm_span.kind.name == "CLIENT"
    assert llm_span.attributes["gen_ai.operation.name"] == "chat"
    assert llm_span.attributes["gen_ai.provider.name"] == "google_genai"
    assert llm_span.attributes["gen_ai.request.model"] == "gemini-pro"
    assert llm_span.attributes["gen_ai.response.model"] == "gemini-pro"
    assert llm_span.attributes["gen_ai.response.finish_reasons"] == ("stop",)
    assert llm_span.attributes["gen_ai.usage.input_tokens"] == 11
    assert llm_span.attributes["gen_ai.usage.output_tokens"] == 4
    assert llm_span.attributes["gen_ai.usage.total_tokens"] == 15
    assert llm_span.attributes["session.id"] == "session-1"
    assert llm_span.attributes["user.id"] == "user-1"
    assert "input.value" in llm_span.attributes
    assert "output.value" in llm_span.attributes


def test_otel_recorder_uses_remote_parent_without_truncating_ids(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "options": {"processor": "simple"},
        }
    )
    trace_id = "1" * 32
    parent_span_id = "2" * 16
    span_id = "3" * 16

    telemetry.recorder.record(
        {
            "type": "span_start",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": "agent.turn",
            "kind": "server",
            "timestamp": "2026-01-01T00:00:00.000000000Z",
            "attributes": {"agent.name": "remote-agent"},
        }
    )
    telemetry.recorder.record(
        {
            "type": "span_end",
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": "agent.turn",
            "kind": "server",
            "timestamp": "2026-01-01T00:00:00.100000000Z",
            "status": "ok",
            "attributes": {},
        }
    )

    telemetry.flush()
    span = exporter.get_finished_spans()[0]
    assert span.context.trace_id == int(trace_id, 16)
    assert span.context.span_id == int(span_id, 16)
    assert span.parent.span_id == int(parent_span_id, 16)
    assert otel_encoder._span_id_to_int("4" * 32) is None


def test_otel_recorder_sets_current_span_context_in_caller_task(monkeypatch) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "options": {"processor": "simple"},
        }
    )

    with telemetry.span("agent.turn") as parent:
        # This is the invariant that must hold for auto-instrumented libraries:
        # record() attaches the AUTOMA span in the same task running the work.
        current_parent = otel_trace.get_current_span().get_span_context()
        assert current_parent.trace_id == int(parent.trace_id, 16)
        assert current_parent.span_id == int(parent.span_id, 16)

        with telemetry.span("tool.call") as child:
            current_child = otel_trace.get_current_span().get_span_context()
            assert current_child.trace_id == int(child.trace_id, 16)
            assert current_child.span_id == int(child.span_id, 16)

        restored_parent = otel_trace.get_current_span().get_span_context()
        assert restored_parent.span_id == int(parent.span_id, 16)

    assert not otel_trace.get_current_span().get_span_context().is_valid


def test_otel_recorder_ends_span_when_scope_exits_from_foreign_context(
    monkeypatch, caplog
) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "options": {"processor": "simple"},
        }
    )
    trace_id = "1" * 32
    span_id = "2" * 16

    start_record = {
        "type": "span_start",
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": None,
        "name": "agent.turn",
        "kind": "server",
        "timestamp": "2026-01-01T00:00:00.000000000Z",
        "attributes": {},
    }
    end_record = {
        "type": "span_end",
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": None,
        "name": "agent.turn",
        "kind": "server",
        "timestamp": "2026-01-01T00:00:00.100000000Z",
        "status": "ok",
        "attributes": {},
    }

    contextvars.Context().run(telemetry.recorder.record, start_record)
    telemetry.recorder.record(end_record)
    telemetry.flush()

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].context.trace_id == int(trace_id, 16)
    assert spans[0].context.span_id == int(span_id, 16)
    assert spans[0].status.status_code.name == "OK"
    assert "Failed to detach context" not in caplog.text


def test_otel_recorder_close_ends_all_spans_with_foreign_scope_contexts(
    monkeypatch,
) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "options": {"processor": "simple"},
        }
    )

    for value in ("2", "3"):
        contextvars.Context().run(
            telemetry.recorder.record,
            {
                "type": "span_start",
                "trace_id": "1" * 32,
                "span_id": value * 16,
                "parent_span_id": None,
                "name": f"span-{value}",
                "kind": "internal",
                "timestamp": "2026-01-01T00:00:00.000000000Z",
                "attributes": {},
            },
        )

    telemetry.close()

    spans = exporter.get_finished_spans()
    assert {span.name for span in spans} == {"span-2", "span-3"}


@pytest.mark.asyncio
async def test_otel_recorder_isolates_concurrent_task_current_spans(
    monkeypatch,
) -> None:
    exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        otel_module,
        "_build_exporter",
        lambda options, otel: exporter,
    )
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "otel",
            "options": {"processor": "simple"},
        }
    )

    async def run_tool(tool_name: str) -> tuple[str, str, str, str]:
        with telemetry.span("tool.call", attributes={"tool.name": tool_name}) as scope:
            start_context = otel_trace.get_current_span().get_span_context()
            await asyncio.sleep(0)
            resumed_context = otel_trace.get_current_span().get_span_context()
            return (
                tool_name,
                scope.span_id,
                f"{start_context.span_id:016x}",
                f"{resumed_context.span_id:016x}",
            )

    results = await asyncio.gather(run_tool("tool_a"), run_tool("tool_b"))

    assert {item[0] for item in results} == {"tool_a", "tool_b"}
    for _tool_name, span_id, start_span_id, resumed_span_id in results:
        assert start_span_id == span_id
        assert resumed_span_id == span_id
    assert not otel_trace.get_current_span().get_span_context().is_valid


def test_otel_timestamp_parser_preserves_nanoseconds() -> None:
    assert (
        otel_encoder.timestamp_ns("2026-01-01T00:00:00.123456789Z")
        == 1_767_225_600_123_456_789
    )
    assert (
        otel_encoder.timestamp_ns("2026-01-01T00:00:00.1Z") == 1_767_225_600_100_000_000
    )
    assert (
        otel_encoder.timestamp_ns("2026-01-01T00:00:00.123456789+01:00")
        == 1_767_222_000_123_456_789
    )
    assert otel_encoder.timestamp_ns("not-a-timestamp") is None


def test_otel_recorder_flush_is_bounded_and_shutdown_is_opt_in() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.force_flush_timeout = None
            self.shutdown_called = False

        def get_tracer(self, *args, **kwargs):
            return SimpleNamespace()

        def force_flush(self, *, timeout_millis):
            self.force_flush_timeout = timeout_millis
            return True

        def shutdown(self):
            self.shutdown_called = True

    provider = FakeProvider()
    recorder = otel_module.OpenTelemetryRecorder(
        TelemetryConfig(
            enabled=True,
            recorder="otel",
            options={"flush_timeout_millis": 1234},
        ),
        tracer_provider=provider,
    )

    recorder.flush()
    recorder.close()

    assert provider.force_flush_timeout == 1234
    assert provider.shutdown_called is False

    shutdown_provider = FakeProvider()
    shutdown_recorder = otel_module.OpenTelemetryRecorder(
        TelemetryConfig(
            enabled=True,
            recorder="otel",
            options={"shutdown_on_close": True},
        ),
        tracer_provider=shutdown_provider,
    )

    shutdown_recorder.close()

    assert shutdown_provider.shutdown_called is True


def test_unknown_enabled_recorder_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="not registered"):
        build_telemetry({"enabled": True, "recorder": "missing_recorder"})


def test_disabled_unknown_recorder_uses_noop() -> None:
    telemetry = build_telemetry({"enabled": False, "recorder": "missing_recorder"})

    with telemetry.span("agent.turn"):
        telemetry.event("message")

    assert telemetry.enabled is False


def test_recorder_registry_rejects_duplicate_without_override() -> None:
    def build_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(base_dir / "telemetry.jsonl")

    def build_other_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(base_dir / "other-telemetry.jsonl")

    register_telemetry_recorder(
        "test_duplicate_recorder",
        build_recorder,
        override=True,
    )

    with pytest.raises(ValueError, match="already registered"):
        register_telemetry_recorder("test_duplicate_recorder", build_other_recorder)


def test_recorder_registry_allows_same_factory_reregistration() -> None:
    def build_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(base_dir / "telemetry.jsonl")

    register_telemetry_recorder(
        "test_same_factory_recorder",
        build_recorder,
        override=True,
    )
    register_telemetry_recorder("test_same_factory_recorder", build_recorder)


def test_recorder_registry_protects_builtin_names() -> None:
    def build_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(base_dir / "telemetry.jsonl")

    with pytest.raises(ValueError, match="built in"):
        register_telemetry_recorder("otel", build_recorder, override=True)


def test_plugin_loading_requires_explicit_opt_in(monkeypatch, tmp_path) -> None:
    loaded = False

    def plugin_factory(config, base_attributes, base_dir):
        return JsonlRecorder(tmp_path / "plugin.jsonl")

    def load_plugin():
        nonlocal loaded
        loaded = True
        return plugin_factory

    entry_points = SimpleNamespace(
        select=lambda group: [
            SimpleNamespace(
                name="test_unrequested_plugin",
                value="pkg:factory",
                load=load_plugin,
            )
        ]
    )
    monkeypatch.setattr(
        telemetry_registry.importlib.metadata,
        "entry_points",
        lambda: entry_points,
    )
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", False)

    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(tmp_path / "local.jsonl")}
    )

    with telemetry.span("agent.turn"):
        pass

    assert loaded is False
    assert "test_unrequested_plugin" not in list_telemetry_recorders()


def test_plugin_loading_skips_bad_plugins_and_marks_loaded(
    monkeypatch, tmp_path, caplog
) -> None:
    class BadEntryPoint:
        name = "test_bad_plugin"
        value = "bad:factory"

        def load(self):
            raise RuntimeError("broken plugin")

    class GoodEntryPoint:
        name = "test_good_plugin"
        value = "good:factory"

        def load(self):
            def build_recorder(config, base_attributes, base_dir):
                return JsonlRecorder(tmp_path / "good.jsonl")

            return build_recorder

    entry_points = SimpleNamespace(
        select=lambda group: [BadEntryPoint(), GoodEntryPoint()]
    )
    monkeypatch.setattr(
        telemetry_registry.importlib.metadata,
        "entry_points",
        lambda: entry_points,
    )
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", False)

    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "test_good_plugin",
            "load_plugins": True,
        }
    )

    with telemetry.span("agent.turn"):
        pass

    assert telemetry_registry._PLUGINS_LOADED is True
    assert "test_good_plugin" in list_telemetry_recorders()
    assert "Skipping telemetry recorder plugin 'test_bad_plugin'" in caplog.text


def test_plugin_loading_cannot_replace_builtin(monkeypatch, tmp_path, caplog) -> None:
    def build_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(tmp_path / "malicious.jsonl")

    entry_points = SimpleNamespace(
        select=lambda group: [
            SimpleNamespace(
                name="jsonl",
                value="malicious:factory",
                load=lambda: build_recorder,
            )
        ]
    )
    monkeypatch.setattr(
        telemetry_registry.importlib.metadata,
        "entry_points",
        lambda: entry_points,
    )
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", False)

    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "jsonl",
            "load_plugins": True,
            "path": str(tmp_path / "safe.jsonl"),
        }
    )

    with telemetry.span("agent.turn"):
        pass
    telemetry.flush()

    assert (tmp_path / "safe.jsonl").exists()
    assert not (tmp_path / "malicious.jsonl").exists()
    assert "built in and cannot be replaced" in caplog.text


def test_plugin_discovery_failure_logs_and_can_retry(monkeypatch, caplog) -> None:
    calls = 0

    def fail_once_entry_points():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("metadata unavailable")
        return SimpleNamespace(select=lambda group: [])

    monkeypatch.setattr(
        telemetry_registry.importlib.metadata,
        "entry_points",
        fail_once_entry_points,
    )
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", False)

    telemetry_registry.load_telemetry_recorder_plugins()

    assert telemetry_registry._PLUGINS_LOADED is False
    assert "Unable to discover telemetry recorder plugins" in caplog.text

    telemetry_registry.load_telemetry_recorder_plugins()

    assert telemetry_registry._PLUGINS_LOADED is True
    assert calls == 2


def test_concurrent_plugin_loading_runs_discovery_once(monkeypatch, tmp_path) -> None:
    calls = 0

    def build_recorder(config, base_attributes, base_dir):
        return JsonlRecorder(tmp_path / "threaded.jsonl")

    def entry_points():
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            select=lambda group: [
                SimpleNamespace(
                    name="test_threaded_plugin",
                    value="threaded:factory",
                    load=lambda: build_recorder,
                )
            ]
        )

    monkeypatch.setattr(
        telemetry_registry.importlib.metadata,
        "entry_points",
        entry_points,
    )
    monkeypatch.setattr(telemetry_registry, "_PLUGINS_LOADED", False)

    threads = [
        threading.Thread(target=telemetry_registry.load_telemetry_recorder_plugins)
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert calls == 1
    assert "test_threaded_plugin" in list_telemetry_recorders()


def test_span_start_failure_restores_context_without_raising(caplog) -> None:
    class FailingRecorder:
        def record(self, item):
            raise OSError("cannot write telemetry")

        def flush(self):
            raise OSError("cannot flush telemetry")

        def close(self):
            raise OSError("cannot close telemetry")

    telemetry = Telemetry(
        config=TelemetryConfig(enabled=True),
        recorder=FailingRecorder(),
    )

    with telemetry.span("agent.turn"):
        telemetry.event("message")
    telemetry.flush()
    telemetry.close()

    assert current_trace_id() is None
    assert current_span_id() is None
    assert "Telemetry record failed" in caplog.text
    assert "Telemetry flush failed" in caplog.text
    assert "Telemetry close failed" in caplog.text


def test_exception_message_is_sanitized_in_metadata_mode(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {
            "enabled": True,
            "recorder": "jsonl",
            "path": str(path),
            "content_mode": "metadata",
        }
    )

    with pytest.raises(RuntimeError):
        with telemetry.span("agent.turn"):
            raise RuntimeError("Authorization: Bearer abcdefghijklmnop")

    telemetry.flush()
    records = _read_jsonl(path)
    message = records[-1]["attributes"]["exception.message"]
    assert message["length"] > 0
    assert message["sha256"]
    assert "content" not in message


def test_content_hash_uses_canonical_mapping_form() -> None:
    from automa_ai.telemetry.redaction import content_hash

    assert content_hash({"b": 2, "a": 1}) == content_hash({"a": 1, "b": 2})


def test_telemetry_config_from_string() -> None:
    cfg = TelemetryConfig.from_value("jsonl")

    assert cfg.enabled is True
    assert cfg.recorder == "jsonl"


def test_wrap_langchain_tool_records_tool_span(tmp_path) -> None:
    async def add_numbers(a: int, b: int) -> dict:
        return {"total": a + b}

    tool = StructuredTool.from_function(
        name="add_numbers",
        description="Add two numbers.",
        coroutine=add_numbers,
    )
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(path)}
    )
    wrapped = wrap_langchain_tool(tool, telemetry, source_type="binding")

    result = asyncio.run(wrapped.ainvoke({"a": 2, "b": 3}))

    assert result == {"total": 5}
    telemetry.flush()
    records = _read_jsonl(path)
    assert [record["name"] for record in records] == [
        "tool.call",
        "tool.input",
        "tool.output",
        "tool.call",
    ]
    assert records[0]["type"] == "span_start"
    assert records[0]["attributes"]["tool.name"] == "add_numbers"
    assert records[0]["attributes"]["tool.source"] == "binding"


def test_wrap_langchain_tool_preserves_config_and_execution_fields(tmp_path) -> None:
    async def read_config(value: str, config: RunnableConfig) -> dict:
        return {
            "value": value,
            "request_id": config["metadata"]["request_id"],
        }

    tool = StructuredTool.from_function(
        name="read_config",
        description="Read runtime config.",
        coroutine=read_config,
        return_direct=True,
        metadata={"tool_meta": "kept"},
        tags=["original"],
        handle_tool_error="handled",
        handle_validation_error="invalid",
    )
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(path)}
    )
    wrapped = wrap_langchain_tool(tool, telemetry, source_type="binding")

    result = asyncio.run(
        wrapped.ainvoke(
            {"value": "hello"},
            config={"metadata": {"request_id": "req-1"}},
        )
    )

    assert result == {"value": "hello", "request_id": "req-1"}
    assert wrapped.return_direct is True
    assert wrapped.metadata == {"tool_meta": "kept"}
    assert wrapped.tags == ["original"]
    assert wrapped.handle_tool_error == "handled"
    assert wrapped.handle_validation_error == "invalid"
    assert wrapped._automa_original_response_format == "content"


def test_wrap_langchain_tool_delegates_content_and_artifact_format(tmp_path) -> None:
    async def make_artifact(value: str) -> tuple[str, dict]:
        return f"content:{value}", {"artifact": value}

    tool = StructuredTool.from_function(
        name="make_artifact",
        description="Return content and artifact.",
        coroutine=make_artifact,
        response_format="content_and_artifact",
    )
    path = tmp_path / "telemetry.jsonl"
    telemetry = build_telemetry(
        {"enabled": True, "recorder": "jsonl", "path": str(path)}
    )
    wrapped = wrap_langchain_tool(tool, telemetry, source_type="binding")

    result = asyncio.run(wrapped.ainvoke({"value": "demo"}))

    assert result == "content:demo"
    assert wrapped.response_format == "content"
    assert wrapped._automa_original_response_format == "content_and_artifact"
