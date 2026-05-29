from __future__ import annotations

import json
import asyncio
import contextvars
import threading
from types import SimpleNamespace

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry import (
    Telemetry,
    build_telemetry,
    current_span_id,
    current_trace_id,
    list_telemetry_recorders,
    register_telemetry_recorder,
    wrap_langchain_tool,
)
from automa_ai.telemetry import registry as telemetry_registry
from automa_ai.telemetry.recorders import JsonlRecorder


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
        register_telemetry_recorder("jsonl", build_recorder, override=True)


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
