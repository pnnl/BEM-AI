"""OpenTelemetry recorder for AUTOMA-AI telemetry records."""

from __future__ import annotations

from contextvars import Token
import logging
import threading
from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.otel_encoder import (
    encode_event,
    encode_span_end,
    encode_span_start,
    otel_attributes,
    orphan_span_attributes,
    parent_context,
    span_attributes_from_event,
    span_kind_to_otel,
    timestamp_ns,
)
from automa_ai.telemetry.recorders import TelemetryRecorder
from automa_ai.telemetry.records import (
    EventRecord,
    SpanEndRecord,
    SpanStartRecord,
    SpanStatus,
    parse_telemetry_record,
)

logger = logging.getLogger(__name__)


class OpenTelemetryRecorder:
    """Translate AUTOMA trace/span/event records into OpenTelemetry spans.

    Important context invariant: recording must stay synchronous on the caller's
    thread/task. The recorder attaches started spans to OpenTelemetry's current
    context with ``context.attach(trace.set_span_in_context(...))`` so
    auto-instrumented work inside the agent or tool sees the AUTOMA span as its
    parent. Moving record() onto a background queue/thread would attach the span
    in the worker context instead, breaking parent-child correlation for
    libraries such as httpx or botocore.
    """

    def __init__(
        self,
        config: TelemetryConfig,
        base_attributes: dict[str, Any] | None = None,
        *,
        tracer_provider: Any | None = None,
        exporter: Any | None = None,
    ) -> None:
        otel = _import_otel()
        self._otel = otel
        self._lock = threading.Lock()
        self._closed = False
        self._spans: dict[str, Any] = {}
        self._span_tokens: dict[str, Any] = {}
        options = config.options or {}
        self._flush_timeout_millis = int(
            options.get("flush_timeout_millis", options.get("timeout_millis", 5000))
        )
        self._flush_on_close = bool(options.get("flush_on_close", False))
        self._shutdown_on_close = bool(options.get("shutdown_on_close", False))
        self._id_generator = _AutomaIdGenerator(otel)
        self._provider = tracer_provider or _build_tracer_provider(
            config,
            base_attributes or {},
            exporter=exporter,
            otel=otel,
            id_generator=self._id_generator,
        )
        self._tracer = self._provider.get_tracer(
            options.get("instrumentation_name", "automa_ai.telemetry"),
            options.get("instrumentation_version"),
        )

    def record(self, item: dict[str, Any]) -> None:
        with self._lock:
            if self._closed:
                logger.warning(
                    "Dropping telemetry item because OpenTelemetry recorder is closed."
                )
                return
            record = parse_telemetry_record(item)
            if record is None:
                return
            if isinstance(record, EventRecord):
                self._record_event(record)
            elif isinstance(record, SpanEndRecord):
                self._record_span_end(record)
            else:
                self._record_span_start(record)

    def flush(self) -> None:
        force_flush = getattr(self._provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=self._flush_timeout_millis)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for span_id in reversed(list(self._spans)):
                token = self._span_tokens.pop(span_id, None)
                span = self._spans[span_id]
                try:
                    self._detach_token(token)
                finally:
                    span.end()
            self._spans.clear()
            self._closed = True
        if self._flush_on_close:
            self.flush()
        shutdown = getattr(self._provider, "shutdown", None)
        if self._shutdown_on_close and callable(shutdown):
            shutdown()

    def _record_span_start(self, record: SpanStartRecord) -> None:
        encoded = encode_span_start(
            record,
            otel=self._otel,
            active_spans=self._spans,
        )
        if encoded is None:
            return
        with self._id_generator.use(
            trace_id=encoded.trace_id,
            span_id=encoded.otel_span_id,
        ):
            span = self._tracer.start_span(
                encoded.name,
                context=encoded.context,
                kind=encoded.kind,
                attributes=encoded.attributes,
                start_time=encoded.start_time,
            )
        token = self._otel.context.attach(self._otel.trace.set_span_in_context(span))
        self._span_tokens[encoded.span_id] = token
        self._spans[encoded.span_id] = span

    def _record_span_end(self, record: SpanEndRecord) -> None:
        encoded = encode_span_end(record, otel=self._otel)
        span = self._spans.pop(encoded.span_id or "", None)
        if span is None:
            self._record_orphan_span_end(record, encoded)
            return

        token = self._span_tokens.pop(encoded.span_id or "", None)
        try:
            if encoded.attributes:
                span.set_attributes(encoded.attributes)
            if encoded.status is not None:
                span.set_status(encoded.status)
            self._detach_token(token)
        finally:
            span.end(end_time=encoded.end_time)

    def _record_event(self, record: EventRecord) -> None:
        encoded = encode_event(record)
        span = self._spans.get(str(encoded.span_id)) if encoded.span_id else None
        if span is not None:
            if record.name == "model.usage" and encoded.attributes:
                span.set_attributes(encoded.attributes)
            promoted_attributes = span_attributes_from_event(
                record.name,
                encoded.attributes,
            )
            if promoted_attributes:
                span.set_attributes(promoted_attributes)
            span.add_event(
                encoded.name,
                attributes=encoded.attributes,
                timestamp=encoded.timestamp,
            )
            return

        self._record_orphan_event(record, encoded.attributes)

    def _record_orphan_span_end(self, record: SpanEndRecord, encoded: Any) -> None:
        span = self._tracer.start_span(
            record.name or "automa.orphan_span_end",
            context=parent_context(
                record.trace_id,
                record.parent_span_id,
                self._spans,
                self._otel,
            ),
            kind=span_kind_to_otel(record.kind, self._otel),
            attributes=orphan_span_attributes(record),
            start_time=encoded.end_time,
        )
        if record.status is SpanStatus.ERROR and encoded.status is not None:
            span.set_status(encoded.status)
        span.end(end_time=encoded.end_time)

    def _record_orphan_event(
        self,
        record: EventRecord,
        attributes: dict[str, Any],
    ) -> None:
        span = self._tracer.start_span(
            record.name or "automa.event",
            context=None,
            kind=self._otel.SpanKind.INTERNAL,
            attributes={
                **attributes,
                "automa.orphan_event": True,
            },
            start_time=timestamp_ns(record.timestamp),
        )
        span.end(end_time=timestamp_ns(record.timestamp))

    @staticmethod
    def _detach_token(token: Any | None) -> None:
        if token is None:
            return
        try:
            token.var.reset(token)
        except ValueError as exc:
            if "different Context" not in str(exc):
                logger.debug("OTEL context detach failed.", exc_info=True)
                return
            old_value = {} if token.old_value is Token.MISSING else token.old_value
            token.var.set(old_value)
            logger.debug("OTEL context token restored from foreign context.")
        except Exception:
            logger.debug("OTEL context detach failed.", exc_info=True)


def build_otel_recorder(
    config: TelemetryConfig,
    base_attributes: dict[str, Any],
    _base_dir: str | Path | None,
) -> TelemetryRecorder:
    """Build an OpenTelemetry recorder from declarative telemetry config."""
    return OpenTelemetryRecorder(config, base_attributes)


def _build_tracer_provider(
    config: TelemetryConfig,
    base_attributes: dict[str, Any],
    *,
    exporter: Any | None,
    otel: Any,
    id_generator: Any,
) -> Any:
    options = config.options or {}
    resource_attributes = otel_attributes(
        {
            "service.name": config.service_name,
            "deployment.environment": config.environment,
            **config.attributes,
            **base_attributes,
            **dict(options.get("resource_attributes") or {}),
        }
    )
    provider = otel.TracerProvider(
        resource=otel.Resource.create(resource_attributes),
        shutdown_on_exit=bool(options.get("shutdown_on_exit", True)),
        id_generator=id_generator,
    )
    span_exporter = exporter or _build_exporter(options, otel)
    processor_type = str(options.get("processor", "batch")).lower()
    if processor_type == "simple":
        provider.add_span_processor(otel.SimpleSpanProcessor(span_exporter))
    elif processor_type == "batch":
        provider.add_span_processor(otel.BatchSpanProcessor(span_exporter))
    else:
        raise ValueError("OTEL telemetry processor must be 'batch' or 'simple'.")
    return provider


class _AutomaIdGenerator:
    def __init__(self, otel: Any) -> None:
        self._fallback = otel.RandomIdGenerator()
        self._local = threading.local()

    def use(self, *, trace_id: int | None, span_id: int | None) -> "_IdOverride":
        return _IdOverride(self, trace_id=trace_id, span_id=span_id)

    def generate_trace_id(self) -> int:
        trace_id = getattr(self._local, "trace_id", None)
        if trace_id is not None:
            return trace_id
        return self._fallback.generate_trace_id()

    def generate_span_id(self) -> int:
        span_id = getattr(self._local, "span_id", None)
        if span_id is not None:
            return span_id
        return self._fallback.generate_span_id()


class _IdOverride:
    def __init__(
        self,
        generator: _AutomaIdGenerator,
        *,
        trace_id: int | None,
        span_id: int | None,
    ) -> None:
        self._generator = generator
        self._trace_id = trace_id
        self._span_id = span_id
        self._previous_trace_id: int | None = None
        self._previous_span_id: int | None = None

    def __enter__(self) -> None:
        self._previous_trace_id = getattr(self._generator._local, "trace_id", None)
        self._previous_span_id = getattr(self._generator._local, "span_id", None)
        self._generator._local.trace_id = self._trace_id
        self._generator._local.span_id = self._span_id

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._generator._local.trace_id = self._previous_trace_id
        self._generator._local.span_id = self._previous_span_id
        return False


def _build_exporter(options: dict[str, Any], otel: Any) -> Any:
    exporter_type = str(options.get("exporter", "otlp_http")).lower()
    endpoint = options.get("endpoint")
    headers = _normalize_headers(options.get("headers"))
    timeout = options.get("timeout")
    if exporter_type in {"otlp", "otlp_http", "http"}:
        return otel.HttpOTLPSpanExporter(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout,
        )
    if exporter_type in {"otlp_grpc", "grpc"}:
        return otel.GrpcOTLPSpanExporter(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout,
            insecure=options.get("insecure"),
        )
    if exporter_type == "console":
        return otel.ConsoleSpanExporter()
    raise ValueError(
        "OTEL telemetry exporter must be 'otlp_http', 'otlp_grpc', or 'console'."
    )


def _import_otel() -> Any:
    try:
        from opentelemetry import trace
        from opentelemetry import context as context_api
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcOTLPSpanExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpOTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )
        from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
        from opentelemetry.trace import (
            NonRecordingSpan,
            SpanContext,
            SpanKind,
            Status,
            StatusCode,
            TraceFlags,
            TraceState,
        )
    except ImportError as exc:
        raise RuntimeError(
            "OTEL telemetry recorder requires OpenTelemetry dependencies. "
            "Install automa_ai with the 'otel' extra or install "
            "opentelemetry-sdk and opentelemetry-exporter-otlp."
        ) from exc

    class OTel:
        pass

    otel = OTel()
    otel.context = context_api
    otel.trace = trace
    otel.BatchSpanProcessor = BatchSpanProcessor
    otel.ConsoleSpanExporter = ConsoleSpanExporter
    otel.GrpcOTLPSpanExporter = GrpcOTLPSpanExporter
    otel.HttpOTLPSpanExporter = HttpOTLPSpanExporter
    otel.NonRecordingSpan = NonRecordingSpan
    otel.RandomIdGenerator = RandomIdGenerator
    otel.Resource = Resource
    otel.SimpleSpanProcessor = SimpleSpanProcessor
    otel.SpanContext = SpanContext
    otel.SpanKind = SpanKind
    otel.Status = Status
    otel.StatusCode = StatusCode
    otel.TraceFlags = TraceFlags
    otel.TraceState = TraceState
    otel.TracerProvider = TracerProvider
    return otel


def _normalize_headers(value: Any) -> dict[str, str] | str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, str):
        headers: dict[str, str] = {}
        for pair in value.split(","):
            if "=" not in pair:
                continue
            key, item = pair.split("=", 1)
            key = key.strip()
            if key:
                headers[key] = item.strip()
        return headers or value
    return value
