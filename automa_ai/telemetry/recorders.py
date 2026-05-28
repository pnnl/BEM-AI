"""Telemetry recorder implementations."""

from __future__ import annotations

import json
import queue
import threading
import atexit
from pathlib import Path
from typing import Any, Protocol


class TelemetryRecorder(Protocol):
    def record(self, item: dict[str, Any]) -> None:
        """Record one telemetry item."""

    def flush(self) -> None:
        """Wait until records accepted so far are persisted."""

    def close(self) -> None:
        """Stop the recorder and release resources."""


class NoopRecorder:
    def record(self, item: dict[str, Any]) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class JsonlRecorder:
    """Append telemetry records to a local JSONL file from a writer thread."""

    _STOP = object()

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._error: BaseException | None = None
        self._closed = False
        self._state_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._writer_loop,
            name=f"automa-jsonl-telemetry:{self.path}",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self._close_at_exit)

    def record(self, item: dict[str, Any]) -> None:
        with self._state_lock:
            if self._closed:
                raise RuntimeError("Cannot record telemetry after recorder is closed.")
            if self._error is not None:
                raise self._error
            self._queue.put(item)

    def flush(self) -> None:
        self._queue.join()
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._queue.put(self._STOP)
        self._queue.join()
        self._thread.join(timeout=5)
        if self._error is not None:
            raise self._error

    def _close_at_exit(self) -> None:
        try:
            self.close()
        except Exception:
            return

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                if self._error is None:
                    self._write_item(item)
            except BaseException as exc:
                self._error = exc
            finally:
                self._queue.task_done()

    def _write_item(self, item: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(item, default=str, ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")


class OpenTelemetryRecorder:
    """Export telemetry records through OpenTelemetry OTLP spans."""

    def __init__(
        self,
        *,
        service_name: str,
        environment: str,
        attributes: dict[str, Any] | None = None,
    ):
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError as exc:
            raise ImportError(
                "OpenTelemetry telemetry recorder requires optional dependencies: "
                "opentelemetry-api, opentelemetry-sdk, and "
                "opentelemetry-exporter-otlp-proto-grpc."
            ) from exc

        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": environment,
                **(attributes or {}),
            }
        )
        self._trace = trace
        self._provider = TracerProvider(resource=resource)
        self._processor = BatchSpanProcessor(OTLPSpanExporter())
        self._provider.add_span_processor(self._processor)
        self._tracer = self._provider.get_tracer("automa-ai")
        self._spans: dict[str, Any] = {}

    def record(self, item: dict[str, Any]) -> None:
        record_type = item.get("type")
        if record_type == "span_start":
            self._start_span(item)
        elif record_type == "event":
            self._record_event(item)
        elif record_type == "span_end":
            self._end_span(item)

    def flush(self) -> None:
        self._provider.force_flush()

    def close(self) -> None:
        self._provider.shutdown()

    def _start_span(self, item: dict[str, Any]) -> None:
        span_id = str(item.get("span_id") or "")
        parent_span_id = item.get("parent_span_id")
        parent_span = self._spans.get(str(parent_span_id)) if parent_span_id else None
        context = self._trace.set_span_in_context(parent_span) if parent_span else None
        span = self._tracer.start_span(
            str(item.get("name") or "automa.span"),
            context=context,
            kind=_span_kind(str(item.get("kind") or "internal")),
            attributes=_otel_attributes(item.get("attributes")),
        )
        if span_id:
            self._spans[span_id] = span

    def _record_event(self, item: dict[str, Any]) -> None:
        span = self._spans.get(str(item.get("span_id")))
        if span is None:
            return
        span.add_event(
            str(item.get("name") or "automa.event"),
            attributes=_otel_attributes(item.get("attributes")),
        )

    def _end_span(self, item: dict[str, Any]) -> None:
        span_id = str(item.get("span_id") or "")
        span = self._spans.pop(span_id, None)
        if span is None:
            return
        if str(item.get("status") or "ok").lower() == "error":
            from opentelemetry.trace import Status, StatusCode

            span.set_status(Status(StatusCode.ERROR))
        for key, value in _otel_attributes(item.get("attributes")).items():
            span.set_attribute(key, value)
        duration_ms = item.get("duration_ms")
        if duration_ms is not None:
            span.set_attribute("automa.duration_ms", float(duration_ms))
        span.end()


def _span_kind(kind: str):
    from opentelemetry.trace import SpanKind

    return {
        "server": SpanKind.SERVER,
        "client": SpanKind.CLIENT,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
        "internal": SpanKind.INTERNAL,
    }.get(kind.lower(), SpanKind.INTERNAL)


def _otel_attributes(attributes: Any) -> dict[str, Any]:
    if not isinstance(attributes, dict):
        return {}
    normalized = {}
    for key, value in attributes.items():
        otel_value = _otel_value(value)
        if otel_value is not None:
            normalized[str(key)] = otel_value
    return normalized


def _otel_value(value: Any) -> Any:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, list | tuple):
        if all(isinstance(item, str | bool | int | float) for item in value):
            return list(value)
    return json.dumps(value, default=str, sort_keys=True)
