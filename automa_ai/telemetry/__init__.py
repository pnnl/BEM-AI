"""Local-first telemetry facade for AUTOMA-AI agents."""

from automa_ai.telemetry.config import build_telemetry
from automa_ai.telemetry.context import current_span_id, current_trace_id
from automa_ai.telemetry.facade import Telemetry
from automa_ai.telemetry.langchain import wrap_langchain_tool
from automa_ai.telemetry.recorders import JsonlRecorder, NoopRecorder, TelemetryRecorder
from automa_ai.telemetry.redaction import sanitize_mapping, sanitize_text

__all__ = [
    "Telemetry",
    "TelemetryRecorder",
    "JsonlRecorder",
    "NoopRecorder",
    "build_telemetry",
    "current_span_id",
    "current_trace_id",
    "sanitize_mapping",
    "sanitize_text",
    "wrap_langchain_tool",
]
