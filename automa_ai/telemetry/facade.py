"""Trace/span/event facade used by AUTOMA-AI runtime code."""

from __future__ import annotations

import asyncio
import time
import traceback
import secrets
import logging
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
from automa_ai.telemetry.redaction import sanitize_mapping, sanitize_text

logger = logging.getLogger(__name__)


def _new_trace_id() -> str:
    """Generate a 128-bit trace id compatible with OpenTelemetry."""
    return _new_hex_id(16)


def _new_span_id() -> str:
    """Generate a 64-bit span id compatible with OpenTelemetry."""
    return _new_hex_id(8)


def _new_hex_id(num_bytes: int) -> str:
    value = secrets.token_hex(num_bytes)
    while set(value) == {"0"}:
        value = secrets.token_hex(num_bytes)
    return value


def _now_ns() -> int:
    """Use monotonic nanoseconds for duration math."""
    return time.monotonic_ns()


def _now_iso() -> str:
    """Return an ISO-like UTC timestamp for JSONL readability."""
    wall_time_ns = time.time_ns()
    wall_time_s = wall_time_ns // 1_000_000_000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(wall_time_s)) + (
        f".{wall_time_ns % 1_000_000_000:09d}Z"
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
        trace_id = current_trace_id() or _new_trace_id()
        span_id = current_span_id()
        item = {
            "type": "event",
            "trace_id": trace_id,
            "span_id": span_id,
            "name": name,
            "timestamp": _now_iso(),
            "attributes": self._attributes(attributes),
        }
        self._record(item)

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

    def flush(self) -> None:
        """Block until the recorder has persisted accepted telemetry items."""
        try:
            self.recorder.flush()
        except Exception:
            logger.warning("Telemetry flush failed; dropping telemetry.", exc_info=True)

    def close(self) -> None:
        """Close the underlying recorder when the caller owns its lifecycle."""
        try:
            self.recorder.close()
        except Exception:
            logger.warning("Telemetry close failed; dropping telemetry.", exc_info=True)

    async def aflush(self) -> None:
        """Run blocking recorder flush work off the event loop."""
        await asyncio.to_thread(self.flush)

    async def aclose(self) -> None:
        """Run blocking recorder close work off the event loop."""
        await asyncio.to_thread(self.close)

    def _record(self, item: dict[str, Any]) -> bool:
        """Record telemetry without allowing recorder failures into runtime code."""
        try:
            self.recorder.record(item)
            return True
        except Exception:
            logger.warning(
                "Telemetry record failed; dropping telemetry item.",
                exc_info=True,
            )
            return False


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
    _closed: bool = False
    _recording: bool = False

    def __enter__(self) -> "SpanScope":
        if not self.telemetry.enabled:
            return self
        self.trace_id = current_trace_id() or _new_trace_id()
        self.parent_span_id = current_span_id()
        self.span_id = _new_span_id()
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
        recorded = self.telemetry._record(
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
        if not recorded:
            # `record()` can fail after contextvars are already set. Restore the
            # previous trace/span so later work in this async task cannot inherit
            # a span that was not accepted by the recorder.
            self._reset_context()
        else:
            self._recording = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.telemetry.enabled:
            return False
        if self._closed:
            return False
        self._closed = True
        if not self._recording:
            return False
        end_ns = _now_ns()
        attributes: dict[str, Any] = {}
        status = "ok"
        if exc is not None:
            status = "error"
            attributes.update(
                {
                    "exception.type": type(exc).__name__,
                    "exception.message": sanitize_text(
                        str(exc),
                        mode="redacted" if self.telemetry.config.debug else "metadata",
                        max_chars=self.telemetry.config.max_content_chars,
                    ),
                }
            )
            if self.telemetry.config.debug:
                attributes["exception.stacktrace"] = "".join(
                    traceback.format_exception(exc_type, exc, tb)
                )
        self.telemetry._record(
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
        self._reset_context()
        # Returning False preserves normal exception propagation.
        return False

    def _reset_context(self) -> None:
        """Restore the parent context exactly once when a span is done."""
        if self._trace_tokens is not None:
            reset_trace_context(self._trace_tokens)
            self._trace_tokens = None
        elif self._span_token is not None:
            reset_current_span(self._span_token)
            self._span_token = None

    async def __aenter__(self) -> "SpanScope":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return self.__exit__(exc_type, exc, tb)
