"""Local-first telemetry facade for AUTOMA-AI agents."""

from automa_ai.telemetry.config import build_telemetry
from automa_ai.telemetry.context import current_span_id, current_trace_id
from automa_ai.telemetry.facade import Telemetry
from automa_ai.telemetry.langchain_llm import AutomaLLMCallbackHandler
from automa_ai.telemetry.langchain import wrap_langchain_tool
from automa_ai.telemetry.otel import OpenTelemetryRecorder
from automa_ai.telemetry.recorders import (
    JsonlRecorder,
    NoopRecorder,
    TelemetryRecorder,
)
from automa_ai.telemetry.redaction import sanitize_mapping, sanitize_text
from automa_ai.telemetry.registry import (
    TelemetryRecorderFactory,
    get_telemetry_recorder_factory,
    list_telemetry_recorders,
    load_telemetry_recorder_plugins,
    register_telemetry_recorder,
)

__all__ = [
    "Telemetry",
    "AutomaLLMCallbackHandler",
    "TelemetryRecorder",
    "JsonlRecorder",
    "NoopRecorder",
    "OpenTelemetryRecorder",
    "TelemetryRecorderFactory",
    "build_telemetry",
    "current_span_id",
    "current_trace_id",
    "get_telemetry_recorder_factory",
    "list_telemetry_recorders",
    "load_telemetry_recorder_plugins",
    "register_telemetry_recorder",
    "sanitize_mapping",
    "sanitize_text",
    "wrap_langchain_tool",
]
