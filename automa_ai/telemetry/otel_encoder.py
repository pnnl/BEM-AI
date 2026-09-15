"""OpenTelemetry encoding helpers for AUTOMA telemetry records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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

# `redaction.sanitize_text` wraps every payload in a
# `{length, sha256, content?, truncated?}` envelope. That shape is correct for
# the AUTOMA record (and the JSONL recorder), but OTEL payload attributes are
# display fields: backends render `input.value` / `output.value` as the prompt
# and completion. Exporting the envelope makes them render an opaque object
# instead of the conversation, so the envelope is flattened during OTEL encoding.
_ENVELOPE_REQUIRED_KEYS = frozenset({"length", "sha256"})
_ENVELOPE_KEYS = frozenset({"content", "length", "sha256", "truncated"})
_ENVELOPE_METADATA_KEYS = ("length", "sha256", "truncated")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class _WithheldPayload:
    """Sentinel for content the redaction policy chose not to export."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<withheld>"


_WITHHELD = _WithheldPayload()


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


def span_attributes_from_event(
    event_name: str | None,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    """Return span-level OTEL attributes implied by an AUTOMA event.

    AUTOMA records rich message/tool/model details as events. Some OTEL
    backends, including LLM observability tools, primarily populate preview and
    usage UI from span attributes. This helper promotes a small, stable subset
    of event attributes without removing the original event.
    """
    if event_name == "message":
        role = attributes.get("message.role")
        content = attributes.get("message.content")
        if role == "user" and content is not None:
            return {
                "input.value": content,
                "gen_ai.prompt": content,
            }
        if role == "assistant" and content is not None:
            return {
                "output.value": content,
                "gen_ai.completion": content,
            }
    elif event_name == "tool.input":
        arguments = attributes.get("tool.arguments")
        if arguments is not None:
            return {"input.value": arguments}
    elif event_name == "tool.output":
        result = attributes.get("tool.result")
        if result is not None:
            return {"output.value": result}
    elif event_name == "llm.output":
        # The callback learns output/model fields only when LangChain finishes
        # the run. Promote the event payload onto the open LLM span so
        # span-oriented backends can render model output without parsing events.
        #
        # NOTE: callers pass raw (pre-otel_attributes) values here. Verify that
        # the recorded OTEL span for llm.output events also goes through
        # otel_attributes so envelope values are unwrapped before promotion.
        #
        # Use explicit None check rather than `or` so that a deliberate empty
        # string ("") is preserved and doesn't fall through to a stale sibling.
        output = attributes.get("output.value")
        if output is None:
            output = attributes.get("gen_ai.completion")
        result = {}
        if output is not None:
            result["output.value"] = output
            result["gen_ai.completion"] = output
        if "gen_ai.response.model" in attributes:
            result["gen_ai.response.model"] = attributes["gen_ai.response.model"]
        if "model.response_name" in attributes:
            result["model.response_name"] = attributes["model.response_name"]
        if "gen_ai.response.finish_reasons" in attributes:
            result["gen_ai.response.finish_reasons"] = attributes[
                "gen_ai.response.finish_reasons"
            ]
        return result
    return {}


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
    elif span_name == "llm.call":
        # LangChain callbacks start AUTOMA spans named `llm.call`; encode them
        # as OTEL GenAI inference spans for backend interoperability.
        enriched.setdefault("gen_ai.operation.name", "chat")
        enriched.setdefault("gen_ai.provider.name", "langchain")
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
        enriched.setdefault(
            "gen_ai.usage.prompt_tokens",
            enriched["model.usage.input_tokens"],
        )
    if "model.usage.output_tokens" in enriched:
        enriched.setdefault(
            "gen_ai.usage.output_tokens",
            enriched["model.usage.output_tokens"],
        )
        enriched.setdefault(
            "gen_ai.usage.completion_tokens",
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
    if operation in {"chat", "generate_content", "text_completion", "embeddings"}:
        model = attributes.get("gen_ai.request.model")
        if model:
            # OTEL GenAI recommends `{operation} {request.model}` for inference
            # span names. This also makes Langfuse timelines easier to scan.
            return f"{operation} {model}"
    return str(operation)


def otel_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Encode AUTOMA attributes as OTEL attributes.

    Redaction envelopes are unwrapped to their content so payload attributes
    stay renderable. For top-level envelopes, the envelope's own metadata is
    preserved on sibling keys (`<key>.length`, `<key>.sha256`, `<key>.truncated`).
    Metadata from nested envelopes is not propagated — the sibling-key approach
    is only applied at the top level of the attribute dict.

    When a mode such as `metadata` withholds content entirely, the payload
    attribute is dropped rather than exported as a hash object a backend would
    display as the prompt.

    Precedence rule: if the input already contains an explicit attribute whose
    key matches a generated sibling key (e.g. `foo.sha256`), the explicit value
    wins. Envelope metadata is merged last via setdefault so input dict ordering
    never changes the result.
    """
    result: dict[str, Any] = {}
    # Collect envelope metadata separately; merging it after the main pass
    # ensures an explicit `foo.sha256` attribute is never silently overwritten
    # by metadata generated from a `foo` envelope, regardless of dict order.
    envelope_meta: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        key_text = str(key)
        if _is_sanitized_envelope(value):
            for name in _ENVELOPE_METADATA_KEYS:
                if name in value:
                    envelope_meta[f"{key_text}.{name}"] = value[name]
        unwrapped = _unwrap_payload(value)
        if unwrapped is _WITHHELD:
            continue
        result[key_text] = _otel_attribute_value(unwrapped)
    # Fill envelope metadata only where the main pass did not already write an
    # explicit attribute — explicit attribute always takes precedence.
    for meta_key, meta_value in envelope_meta.items():
        result.setdefault(meta_key, meta_value)
    return result


def _is_sanitized_envelope(value: Any) -> bool:
    """Detect a `redaction.sanitize_text` envelope without matching real payloads."""
    if not isinstance(value, Mapping):
        return False
    keys = set(value)
    if not _ENVELOPE_REQUIRED_KEYS <= keys or not keys <= _ENVELOPE_KEYS:
        return False
    length = value.get("length")
    sha256 = value.get("sha256")
    if isinstance(length, bool) or not isinstance(length, int):
        return False
    return isinstance(sha256, str) and _SHA256_PATTERN.match(sha256) is not None


def _unwrap_payload(value: Any) -> Any:
    """Recursively replace redaction envelopes with the content they wrap.
    """
    if _is_sanitized_envelope(value):
        return value["content"] if "content" in value else _WITHHELD
    if isinstance(value, Mapping):
        unwrapped_map = {}
        for key, item in value.items():
            item_value = _unwrap_payload(item)
            if item_value is not _WITHHELD:
                unwrapped_map[str(key)] = item_value
        if value and not unwrapped_map:
            return _WITHHELD
        return unwrapped_map
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        unwrapped_list = [
            item
            for item in (_unwrap_payload(entry) for entry in value)
            if item is not _WITHHELD
        ]
        if value and not unwrapped_list:
            return _WITHHELD
        return unwrapped_list
    return value


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
