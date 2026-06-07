"""OpenTelemetry encoding helpers for AUTOMA telemetry records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any

from automa_ai.telemetry.records import (
    EventRecord,
    SpanEndRecord,
    SpanKind,
    SpanStartRecord,
    SpanStatus,
)

_ISO_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<base>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


@dataclass(frozen=True)
class EncodedSpanStart:
    span_id: str
    trace_id: int | None
    otel_span_id: int | None
    name: str
    context: Any | None
    kind: Any
    attributes: dict[str, Any]
    start_time: int | None


@dataclass(frozen=True)
class EncodedSpanEnd:
    span_id: str | None
    status: Any | None
    attributes: dict[str, Any]
    end_time: int | None


@dataclass(frozen=True)
class EncodedEvent:
    span_id: str | None
    name: str
    attributes: dict[str, Any]
    timestamp: int | None


def encode_span_start(
    record: SpanStartRecord,
    *,
    otel: Any,
    active_spans: dict[str, Any],
) -> EncodedSpanStart | None:
    if not record.span_id:
        return None
    semantic_attributes = _semantic_attributes(record.name, dict(record.attributes))
    attributes = otel_attributes(
        {
            **semantic_attributes,
            "automa.trace_id": record.trace_id,
            "automa.span_id": record.span_id,
            "automa.parent_span_id": record.parent_span_id,
        }
    )
    return EncodedSpanStart(
        span_id=record.span_id,
        trace_id=_trace_id_to_int(record.trace_id),
        otel_span_id=_span_id_to_int(record.span_id),
        name=_span_name(record.name or "automa.span", semantic_attributes),
        context=parent_context(
            record.trace_id, record.parent_span_id, active_spans, otel
        ),
        kind=span_kind_to_otel(record.kind, otel),
        attributes=attributes,
        start_time=timestamp_ns(record.timestamp),
    )


def encode_span_end(record: SpanEndRecord, *, otel: Any) -> EncodedSpanEnd:
    status = None
    if record.status is SpanStatus.ERROR:
        status = otel.Status(
            otel.StatusCode.ERROR,
            status_description(record.attributes),
        )
    elif record.status is SpanStatus.OK:
        status = otel.Status(otel.StatusCode.OK)
    return EncodedSpanEnd(
        span_id=record.span_id,
        status=status,
        attributes=otel_attributes(dict(record.attributes)),
        end_time=timestamp_ns(record.timestamp),
    )


def encode_event(record: EventRecord) -> EncodedEvent:
    semantic_attributes = _semantic_attributes(record.name, dict(record.attributes))
    attributes = otel_attributes(
        {
            **semantic_attributes,
            "automa.trace_id": record.trace_id,
            "automa.span_id": record.span_id,
        }
    )
    return EncodedEvent(
        span_id=record.span_id,
        name=record.name or "event",
        attributes=attributes,
        timestamp=timestamp_ns(record.timestamp),
    )


def orphan_span_attributes(record: SpanEndRecord) -> dict[str, Any]:
    return otel_attributes(
        {
            **dict(record.attributes),
            "automa.trace_id": record.trace_id,
            "automa.span_id": record.span_id,
            "automa.parent_span_id": record.parent_span_id,
            "automa.orphan_span_end": True,
        }
    )


def parent_context(
    trace_id: str | None,
    parent_span_id: str | None,
    active_spans: dict[str, Any],
    otel: Any,
) -> Any | None:
    if not parent_span_id:
        return None
    parent = active_spans.get(str(parent_span_id))
    if parent is not None:
        return otel.trace.set_span_in_context(parent)
    return remote_parent_context(trace_id, parent_span_id, otel)


def remote_parent_context(trace_id: Any, parent_span_id: str, otel: Any) -> Any | None:
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


def span_kind_to_otel(kind: SpanKind, otel: Any) -> Any:
    return {
        SpanKind.SERVER: otel.SpanKind.SERVER,
        SpanKind.CLIENT: otel.SpanKind.CLIENT,
        SpanKind.PRODUCER: otel.SpanKind.PRODUCER,
        SpanKind.CONSUMER: otel.SpanKind.CONSUMER,
        SpanKind.INTERNAL: otel.SpanKind.INTERNAL,
    }.get(kind, otel.SpanKind.INTERNAL)


def timestamp_ns(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    match = _ISO_TIMESTAMP_PATTERN.match(value.strip())
    if match is None:
        return None
    tz = match.group("tz") or "+00:00"
    if tz == "Z":
        tz = "+00:00"
    elif len(tz) == 5 and tz[0] in "+-" and ":" not in tz:
        tz = f"{tz[:3]}:{tz[3:]}"
    text = f"{match.group('base')}{tz}"
    fraction = match.group("fraction") or ""
    try:
        epoch_seconds = int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None
    fractional_ns = int(fraction.ljust(9, "0")[:9]) if fraction else 0
    return epoch_seconds * 1_000_000_000 + fractional_ns


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
    if "model.usage.total_tokens" in enriched:
        enriched.setdefault(
            "gen_ai.usage.total_tokens",
            enriched["model.usage.total_tokens"],
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


def otel_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
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


def status_description(attributes: Any) -> str | None:
    if not isinstance(attributes, dict):
        attributes = dict(attributes or {})
    message = attributes.get("exception.message")
    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        return str(message.get("content") or message.get("sha256") or "")
    return None
