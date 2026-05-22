"""Trace/span/event facade used by AUTOMA-AI runtime code."""

from __future__ import annotations

import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.context import (
    current_span_id,
    current_trace_id,
    reset_current_span,
    reset_trace_context,
    set_current_span,
    set_trace_context,
)
from automa_ai.telemetry.recorders import NoopRecorder, TelemetryRecorder
from automa_ai.telemetry.redaction import sanitize_mapping


def _new_id() -> str:
    """Generate an opaque trace/span id for the local recorder."""
    return uuid.uuid4().hex


def _now_ns() -> int:
    """Use monotonic-ish wall clock nanoseconds for duration math."""
    return time.time_ns()


def _now_iso() -> str:
    """Return an ISO-like UTC timestamp for JSONL readability."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + (
        f".{time.time_ns() % 1_000_000_000:09d}Z"
    )


@dataclass
class Telemetry:
    config: TelemetryConfig = field(default_factory=TelemetryConfig)
    recorder: TelemetryRecorder = field(default_factory=NoopRecorder)
    base_attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        """Expose the config flag so instrumentation call sites stay simple."""
        return self.config.enabled

    def span(
        self,
        name: str,
        *,
        kind: str = "internal",
        attributes: dict[str, Any] | None = None,
    ) -> "SpanScope":
        """Create a span context manager without recording until entered."""
        return SpanScope(
            telemetry=self,
            name=name,
            kind=kind,
            attributes=attributes or {},
        )

    def event(
        self,
        name: str,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """Record a point-in-time event on the active span.

        Events emitted without an active span still receive a trace id, which
        makes accidental out-of-span instrumentation visible in JSONL instead
        of silently dropping useful debugging information.
        """
        if not self.enabled:
            return
        trace_id = current_trace_id() or _new_id()
        span_id = current_span_id()
        item = {
            "type": "event",
            "trace_id": trace_id,
            "span_id": span_id,
            "name": name,
            "timestamp": _now_iso(),
            "attributes": self._attributes(attributes),
        }
        self.recorder.record(item)

    def _attributes(self, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
        """Merge global attributes and apply payload sanitization once."""
        merged = {
            "service.name": self.config.service_name,
            "deployment.environment": self.config.environment,
            **self.config.attributes,
            **self.base_attributes,
        }
        if attributes:
            merged.update(attributes)
        return sanitize_mapping(
            merged,
            mode=self.config.content_mode,
            max_chars=self.config.max_content_chars,
        )


@dataclass
class SpanScope:
    telemetry: Telemetry
    name: str
    kind: str
    attributes: dict[str, Any]
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    _start_ns: int | None = None
    _span_token: Any = None
    _trace_tokens: Any = None

    def __enter__(self) -> "SpanScope":
        if not self.telemetry.enabled:
            return self
        self.trace_id = current_trace_id() or _new_id()
        self.parent_span_id = current_span_id()
        self.span_id = _new_id()
        self._start_ns = _now_ns()
        # Starting the first span creates a trace. Nested spans only replace the
        # current span id and keep the parent trace id intact.
        if current_trace_id() is None:
            self._trace_tokens = set_trace_context(
                trace_id=self.trace_id,
                span_id=self.span_id,
            )
        else:
            self._span_token = set_current_span(self.span_id)
        self.telemetry.recorder.record(
            {
                "type": "span_start",
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "name": self.name,
                "kind": self.kind,
                "timestamp": _now_iso(),
                "attributes": self.telemetry._attributes(self.attributes),
            }
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.telemetry.enabled:
            return False
        end_ns = _now_ns()
        attributes: dict[str, Any] = {}
        status = "ok"
        if exc is not None:
            status = "error"
            attributes.update(
                {
                    "exception.type": type(exc).__name__,
                    "exception.message": str(exc),
                }
            )
            if self.telemetry.config.debug:
                attributes["exception.stacktrace"] = "".join(
                    traceback.format_exception(exc_type, exc, tb)
                )
        self.telemetry.recorder.record(
            {
                "type": "span_end",
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "name": self.name,
                "kind": self.kind,
                "timestamp": _now_iso(),
                "status": status,
                "duration_ms": (
                    (end_ns - self._start_ns) / 1_000_000
                    if self._start_ns is not None
                    else None
                ),
                "attributes": self.telemetry._attributes(attributes),
            }
        )
        if self._trace_tokens is not None:
            reset_trace_context(self._trace_tokens)
        elif self._span_token is not None:
            reset_current_span(self._span_token)
        # Returning False preserves normal exception propagation.
        return False

    async def __aenter__(self) -> "SpanScope":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return self.__exit__(exc_type, exc, tb)
