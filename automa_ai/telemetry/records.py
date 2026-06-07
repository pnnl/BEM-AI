"""Pure AUTOMA telemetry record model.

This module intentionally has no OpenTelemetry imports. It models the internal
record shapes emitted by the telemetry facade so recorders can distinguish
AUTOMA data from backend-specific SDK values.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SpanKind(str, Enum):
    INTERNAL = "internal"
    SERVER = "server"
    CLIENT = "client"
    PRODUCER = "producer"
    CONSUMER = "consumer"


class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


@dataclass(frozen=True)
class SpanStartRecord:
    trace_id: str | None
    span_id: str | None
    parent_span_id: str | None
    name: str
    kind: SpanKind
    timestamp: str | None
    attributes: Mapping[str, Any]


@dataclass(frozen=True)
class SpanEndRecord:
    trace_id: str | None
    span_id: str | None
    parent_span_id: str | None
    name: str
    kind: SpanKind
    timestamp: str | None
    status: SpanStatus | None
    duration_ms: float | None
    attributes: Mapping[str, Any]


@dataclass(frozen=True)
class EventRecord:
    trace_id: str | None
    span_id: str | None
    name: str
    timestamp: str | None
    attributes: Mapping[str, Any]


TelemetryRecord = SpanStartRecord | SpanEndRecord | EventRecord


def parse_telemetry_record(item: Mapping[str, Any] | None) -> TelemetryRecord | None:
    """Leniently parse a raw facade dictionary into an AUTOMA record.

    Unknown record types, malformed records, and unsupported enum values should
    never raise into recorder code. The OTEL recorder can skip ``None`` while
    JSONL remains a raw-dict passthrough.
    """
    if not isinstance(item, Mapping):
        return None
    item_type = item.get("type")
    if item_type == "span_start":
        return SpanStartRecord(
            trace_id=_optional_str(item.get("trace_id")),
            span_id=_optional_str(item.get("span_id")),
            parent_span_id=_optional_str(item.get("parent_span_id")),
            name=_str_or_empty(item.get("name")),
            kind=_span_kind(item.get("kind")),
            timestamp=_optional_str(item.get("timestamp")),
            attributes=_attributes(item.get("attributes")),
        )
    if item_type == "span_end":
        return SpanEndRecord(
            trace_id=_optional_str(item.get("trace_id")),
            span_id=_optional_str(item.get("span_id")),
            parent_span_id=_optional_str(item.get("parent_span_id")),
            name=_str_or_empty(item.get("name")),
            kind=_span_kind(item.get("kind")),
            timestamp=_optional_str(item.get("timestamp")),
            status=_span_status(item.get("status")),
            duration_ms=_optional_float(item.get("duration_ms")),
            attributes=_attributes(item.get("attributes")),
        )
    if item_type == "event":
        return EventRecord(
            trace_id=_optional_str(item.get("trace_id")),
            span_id=_optional_str(item.get("span_id")),
            name=_str_or_empty(item.get("name")),
            timestamp=_optional_str(item.get("timestamp")),
            attributes=_attributes(item.get("attributes")),
        )
    return None


def _span_kind(value: Any) -> SpanKind:
    text = str(value or "").lower().replace("-", "_")
    return {
        "server": SpanKind.SERVER,
        "client": SpanKind.CLIENT,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
        "internal": SpanKind.INTERNAL,
    }.get(text, SpanKind.INTERNAL)


def _span_status(value: Any) -> SpanStatus | None:
    text = str(value or "").lower()
    return {
        "ok": SpanStatus.OK,
        "error": SpanStatus.ERROR,
    }.get(text)


def _attributes(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _str_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
