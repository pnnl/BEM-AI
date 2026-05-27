from __future__ import annotations

import json
import asyncio
import threading

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry import (
    Telemetry,
    build_telemetry,
    current_span_id,
    current_trace_id,
    wrap_langchain_tool,
)
from automa_ai.telemetry.recorders import JsonlRecorder


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


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


def test_noop_recorder_does_not_create_path(tmp_path) -> None:
    path = tmp_path / "missing.jsonl"
    telemetry = build_telemetry(
        {"enabled": False, "recorder": "jsonl", "path": str(path)}
    )

    with telemetry.span("agent.turn"):
        telemetry.event("message")

    assert not path.exists()


def test_jsonl_recorder_close_rejects_late_records_without_hanging(tmp_path) -> None:
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
    with pytest.raises(RuntimeError, match="closed"):
        recorder.record({"type": "event", "name": "after-close"})


def test_otel_recorder_is_explicitly_optional() -> None:
    with pytest.raises(ImportError, match="OpenTelemetry"):
        build_telemetry({"enabled": True, "recorder": "otel"})


def test_span_start_failure_restores_context() -> None:
    class FailingRecorder:
        def record(self, item):
            raise OSError("cannot write telemetry")

    telemetry = Telemetry(
        config=TelemetryConfig(enabled=True),
        recorder=FailingRecorder(),
    )

    with pytest.raises(OSError, match="cannot write telemetry"):
        with telemetry.span("agent.turn"):
            pass

    assert current_trace_id() is None
    assert current_span_id() is None


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
