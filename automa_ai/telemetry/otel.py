"""OpenTelemetry recorder for AUTOMA-AI telemetry records."""

from __future__ import annotations

from datetime import datetime
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from automa_ai.config.telemetry import TelemetryConfig
from automa_ai.telemetry.recorders import TelemetryRecorder

logger = logging.getLogger(__name__)
_ISO_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


class OpenTelemetryRecorder:
    """Translate AUTOMA trace/span/event records into OpenTelemetry spans."""

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
            item_type = item.get("type")
            if item_type == "span_start":
                self._record_span_start(item)
            elif item_type == "span_end":
                self._record_span_end(item)
            elif item_type == "event":
                self._record_event(item)

    def flush(self) -> None:
        force_flush = getattr(self._provider, "force_flush", None)
        if callable(force_flush):
            force_flush(timeout_millis=self._flush_timeout_millis)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for span in list(self._spans.values()):
                span.end()
            self._spans.clear()
            self._closed = True
        if self._flush_on_close:
            self.flush()
        shutdown = getattr(self._provider, "shutdown", None)
        if self._shutdown_on_close and callable(shutdown):
            shutdown()

    def _record_span_start(self, item: dict[str, Any]) -> None:
        span_id = str(item.get("span_id") or "")
        if not span_id:
            return
        semantic_attributes = _semantic_attributes(
            str(item.get("name") or ""),
            dict(item.get("attributes") or {}),
        )
        attributes = _otel_attributes(
            {
                **semantic_attributes,
                "automa.trace_id": item.get("trace_id"),
                "automa.span_id": span_id,
                "automa.parent_span_id": item.get("parent_span_id"),
            }
        )
        trace_id = _trace_id_to_int(item.get("trace_id"))
        otel_span_id = _span_id_to_int(span_id)
        with self._id_generator.use(trace_id=trace_id, span_id=otel_span_id):
            span = self._tracer.start_span(
                _span_name(str(item.get("name") or "automa.span"), semantic_attributes),
                context=self._parent_context(item),
                kind=_span_kind(str(item.get("kind") or "internal"), self._otel),
                attributes=attributes,
                start_time=_timestamp_ns(item.get("timestamp")),
            )
        self._spans[span_id] = span

    def _record_span_end(self, item: dict[str, Any]) -> None:
        span_id = str(item.get("span_id") or "")
        span = self._spans.pop(span_id, None)
        if span is None:
            self._record_orphan_span_end(item)
            return

        attributes = _otel_attributes(item.get("attributes") or {})
        if attributes:
            span.set_attributes(attributes)
        if item.get("status") == "error":
            span.set_status(
                self._otel.Status(
                    self._otel.StatusCode.ERROR,
                    _status_description(item.get("attributes") or {}),
                )
            )
        elif item.get("status") == "ok":
            span.set_status(self._otel.Status(self._otel.StatusCode.OK))
        span.end(end_time=_timestamp_ns(item.get("timestamp")))

    def _record_event(self, item: dict[str, Any]) -> None:
        span_id = item.get("span_id")
        span = self._spans.get(str(span_id)) if span_id else None
        semantic_attributes = _semantic_attributes(
            str(item.get("name") or ""),
            dict(item.get("attributes") or {}),
        )
        attributes = _otel_attributes(
            {
                **semantic_attributes,
                "automa.trace_id": item.get("trace_id"),
                "automa.span_id": span_id,
            }
        )
        if span is not None:
            span.add_event(
                str(item.get("name") or "event"),
                attributes=attributes,
                timestamp=_timestamp_ns(item.get("timestamp")),
            )
            return

        self._record_orphan_event(item, attributes)

    def _record_orphan_span_end(self, item: dict[str, Any]) -> None:
        attributes = _otel_attributes(
            {
                **dict(item.get("attributes") or {}),
                "automa.trace_id": item.get("trace_id"),
                "automa.span_id": item.get("span_id"),
                "automa.parent_span_id": item.get("parent_span_id"),
                "automa.orphan_span_end": True,
            }
        )
        span = self._tracer.start_span(
            str(item.get("name") or "automa.orphan_span_end"),
            context=self._parent_context(item),
            kind=_span_kind(str(item.get("kind") or "internal"), self._otel),
            attributes=attributes,
            start_time=_timestamp_ns(item.get("timestamp")),
        )
        if item.get("status") == "error":
            span.set_status(
                self._otel.Status(
                    self._otel.StatusCode.ERROR,
                    _status_description(item.get("attributes") or {}),
                )
            )
        span.end(end_time=_timestamp_ns(item.get("timestamp")))

    def _record_orphan_event(
        self,
        item: dict[str, Any],
        attributes: dict[str, Any],
    ) -> None:
        span = self._tracer.start_span(
            str(item.get("name") or "automa.event"),
            context=self._parent_context(item),
            kind=self._otel.SpanKind.INTERNAL,
            attributes={
                **attributes,
                "automa.orphan_event": True,
            },
            start_time=_timestamp_ns(item.get("timestamp")),
        )
        span.end(end_time=_timestamp_ns(item.get("timestamp")))

    def _parent_context(self, item: dict[str, Any]) -> Any | None:
        parent_span_id = item.get("parent_span_id")
        if parent_span_id:
            parent = self._spans.get(str(parent_span_id))
            if parent is not None:
                return self._otel.trace.set_span_in_context(parent)
            remote_parent = _remote_parent_context(
                item.get("trace_id"),
                str(parent_span_id),
                self._otel,
            )
            if remote_parent is not None:
                return remote_parent
        return None


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
    resource_attributes = _otel_attributes(
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


def _span_kind(kind: str, otel: Any) -> Any:
    normalized = kind.lower().replace("-", "_")
    return {
        "server": otel.SpanKind.SERVER,
        "client": otel.SpanKind.CLIENT,
        "producer": otel.SpanKind.PRODUCER,
        "consumer": otel.SpanKind.CONSUMER,
        "internal": otel.SpanKind.INTERNAL,
    }.get(normalized, otel.SpanKind.INTERNAL)


def _timestamp_ns(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    match = _ISO_TIMESTAMP_PATTERN.match(value.strip())
    if match is None:
        return None
    tz = match.group("tz") or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    text = f"{match.group('base')}{tz}"
    fraction = match.group("fraction") or ""
    try:
        epoch_seconds = int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None
    fractional_ns = int(fraction.ljust(9, "0")[:9]) if fraction else 0
    return epoch_seconds * 1_000_000_000 + fractional_ns


def _remote_parent_context(trace_id: Any, parent_span_id: str, otel: Any) -> Any | None:
    trace_int = _trace_id_to_int(trace_id)
    span_int = _span_id_to_int(parent_span_id)
    if trace_int is None or span_int is None:
        return None
    context = otel.SpanContext(
        trace_id=trace_int,
        span_id=span_int,
        is_remote=True,
        trace_flags=otel.TraceFlags(otel.TraceFlags.SAMPLED),
        trace_state=otel.TraceState(),
    )
    return otel.trace.set_span_in_context(otel.NonRecordingSpan(context))


def _trace_id_to_int(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("-", "")
    if len(text) != 32:
        return None
    try:
        trace_id = int(text, 16)
    except ValueError:
        return None
    return trace_id or None


def _span_id_to_int(value: Any) -> int | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("-", "")
    if len(text) != 16:
        return None
    try:
        span_id = int(text, 16)
    except ValueError:
        return None
    return span_id or None


def _semantic_attributes(span_name: str, attributes: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(attributes)
    if span_name == "agent.turn":
        enriched.setdefault("gen_ai.operation.name", "invoke_agent")
        enriched.setdefault("gen_ai.provider.name", "automa_ai")
        if "agent.name" in enriched:
            enriched.setdefault("gen_ai.agent.name", enriched["agent.name"])
        if "agent.description" in enriched:
            enriched.setdefault(
                "gen_ai.agent.description", enriched["agent.description"]
            )
        if "agent.version" in enriched:
            enriched.setdefault("gen_ai.agent.version", enriched["agent.version"])
        if "model.name" in enriched:
            enriched.setdefault("gen_ai.request.model", enriched["model.name"])
        if "model.provider" in enriched:
            enriched.setdefault("gen_ai.provider.name", enriched["model.provider"])
    elif span_name == "tool.call":
        enriched.setdefault("gen_ai.operation.name", "execute_tool")
        enriched.setdefault("gen_ai.provider.name", "automa_ai")
        if "tool.name" in enriched:
            enriched.setdefault("gen_ai.tool.name", enriched["tool.name"])
    if "model.provider" in enriched:
        enriched.setdefault("gen_ai.provider.name", enriched["model.provider"])
    if "model.name" in enriched:
        enriched.setdefault("gen_ai.request.model", enriched["model.name"])
    if "model.response_name" in enriched:
        enriched.setdefault("gen_ai.response.model", enriched["model.response_name"])
    if "model.usage.input_tokens" in enriched:
        enriched.setdefault(
            "gen_ai.usage.input_tokens",
            enriched["model.usage.input_tokens"],
        )
    if "model.usage.output_tokens" in enriched:
        enriched.setdefault(
            "gen_ai.usage.output_tokens",
            enriched["model.usage.output_tokens"],
        )
    return enriched


def _span_name(original_name: str, attributes: dict[str, Any]) -> str:
    operation = attributes.get("gen_ai.operation.name")
    if not operation:
        return original_name
    if operation == "invoke_agent" and attributes.get("gen_ai.agent.name"):
        return f"{operation} {attributes['gen_ai.agent.name']}"
    if operation == "execute_tool" and attributes.get("gen_ai.tool.name"):
        return f"{operation} {attributes['gen_ai.tool.name']}"
    return str(operation)


def _otel_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        result[str(key)] = _otel_attribute_value(value)
    return result


def _otel_attribute_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, str) for item in value):
            return list(value)
        if all(isinstance(item, bool) for item in value):
            return list(value)
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return list(value)
        if all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in value
        ):
            return list(value)
    return json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)


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


def _status_description(attributes: dict[str, Any]) -> str | None:
    message = attributes.get("exception.message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return str(message.get("content") or message.get("sha256") or "")
    return None
