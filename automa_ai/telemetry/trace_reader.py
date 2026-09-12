"""Read, summarize, and evaluate AUTOMA-AI JSONL telemetry traces."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_MISSING_TRACE_ID = "<missing-trace-id>"
_TOOL_ARGUMENT_EVENTS = frozenset({"tool.input", "tool.requested"})
_TOOL_OUTPUT_EVENTS = frozenset({"tool.output", "tool.message"})


@dataclass(frozen=True)
class ReadIssue:
    line_number: int
    message: str


@dataclass(frozen=True)
class SpanSummary:
    span_id: str
    parent_span_id: str | None
    name: str
    status: str | None
    duration_ms: float | None
    attributes: dict[str, Any]


@dataclass(frozen=True)
class EventSummary:
    name: str
    span_id: str | None
    attributes: dict[str, Any]


@dataclass(frozen=True)
class TraceSummary:
    trace_id: str
    record_count: int
    spans: tuple[SpanSummary, ...]
    events: tuple[EventSummary, ...]
    top_level_duration_ms: float

    @property
    def span_count(self) -> int:
        return len(self.spans)

    @property
    def event_names(self) -> tuple[str, ...]:
        return tuple(sorted({event.name for event in self.events}))

    @property
    def span_names(self) -> tuple[str, ...]:
        return tuple(sorted({span.name for span in self.spans}))

    @property
    def open_spans(self) -> tuple[SpanSummary, ...]:
        return tuple(span for span in self.spans if span.status is None)

    @property
    def error_spans(self) -> tuple[SpanSummary, ...]:
        return tuple(span for span in self.spans if span.status == "error")

    @property
    def open_span_count(self) -> int:
        return len(self.open_spans)

    @property
    def error_span_count(self) -> int:
        return len(self.error_spans)


@dataclass(frozen=True)
class EvaluationFailure:
    trace_id: str
    message: str


def read_jsonl(path: str | Path) -> tuple[list[dict[str, Any]], list[ReadIssue]]:
    """Read valid JSON-object records, reporting malformed lines non-fatally."""
    records: list[dict[str, Any]] = []
    issues: list[ReadIssue] = []
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(ReadIssue(number, f"Invalid JSON: {exc.msg}"))
                continue
            if isinstance(item, dict):
                records.append(item)
            else:
                issues.append(ReadIssue(number, "Expected a JSON object."))
    return records, issues


def summarize_traces(records: Iterable[dict[str, Any]]) -> list[TraceSummary]:
    """Build tool-aware summaries without discarding attributes or call counts."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        trace_id = record.get("trace_id")
        grouped[
            trace_id if isinstance(trace_id, str) and trace_id else _MISSING_TRACE_ID
        ].append(record)
    return [
        _summarize_trace(trace_id, grouped[trace_id]) for trace_id in sorted(grouped)
    ]


def _summarize_trace(trace_id: str, records: Sequence[dict[str, Any]]) -> TraceSummary:
    starts: dict[str, dict[str, Any]] = {}
    ends: dict[str, dict[str, Any]] = {}
    events: list[EventSummary] = []
    for record in records:
        span_id = record.get("span_id")
        if record.get("type") == "span_start" and isinstance(span_id, str) and span_id:
            starts[span_id] = record
        elif record.get("type") == "span_end" and isinstance(span_id, str) and span_id:
            ends[span_id] = record
        elif record.get("type") == "event" and isinstance(record.get("name"), str):
            events.append(
                EventSummary(
                    record["name"],
                    span_id if isinstance(span_id, str) else None,
                    _attributes(record),
                )
            )
    spans = tuple(
        SpanSummary(
            span_id,
            _text(start.get("parent_span_id")),
            _text(start.get("name")) or "<unnamed-span>",
            _text(ends[span_id].get("status")) if span_id in ends else None,
            _number(ends[span_id].get("duration_ms")) if span_id in ends else None,
            _attributes(start),
        )
        for span_id, start in starts.items()
    )
    root_durations = [
        span.duration_ms
        for span in spans
        if (span.parent_span_id is None or span.parent_span_id not in starts)
        and span.duration_ms is not None
    ]
    return TraceSummary(
        trace_id, len(records), spans, tuple(events), max(root_durations, default=0.0)
    )


def evaluate_traces(
    summaries: Sequence[TraceSummary],
    *,
    required_events: Iterable[str] = (),
    forbidden_events: Iterable[str] = (),
    required_spans: Iterable[str] = (),
    required_tools: Iterable[str] = (),
    tool_call_counts: Iterable[str] = (),
    tool_argument_contains: Iterable[str] = (),
    tool_output_contains: Iterable[str] = (),
    max_duration_ms: float | None = None,
    require_ok: bool = False,
) -> list[EvaluationFailure]:
    """Evaluate trace-wide, span, and tool-attribute expectations."""
    if not summaries:
        return [EvaluationFailure(_MISSING_TRACE_ID, "No trace records found.")]
    failures: list[EvaluationFailure] = []
    for summary in summaries:
        for name in sorted(set(required_events) - set(summary.event_names)):
            failures.append(
                EvaluationFailure(summary.trace_id, f"Missing event: {name}")
            )
        for name in sorted(set(forbidden_events) & set(summary.event_names)):
            failures.append(
                EvaluationFailure(summary.trace_id, f"Forbidden event: {name}")
            )
        for name in sorted(set(required_spans) - set(summary.span_names)):
            failures.append(
                EvaluationFailure(summary.trace_id, f"Missing span: {name}")
            )
        tools = tuple(span for span in summary.spans if span.name == "tool.call")
        for name in required_tools:
            if not any(_tool_name(span.attributes) == name for span in tools):
                failures.append(
                    EvaluationFailure(summary.trace_id, f"Missing tool call: {name}")
                )
        for spec in tool_call_counts:
            name, expected = _tool_count(spec)
            actual = sum(_tool_name(span.attributes) == name for span in tools)
            if actual != expected:
                failures.append(
                    EvaluationFailure(
                        summary.trace_id,
                        f"Tool {name} call count is {actual}; expected {expected}.",
                    )
                )
        _tool_content_failures(
            failures,
            summary,
            tool_argument_contains,
            "tool.arguments",
            _TOOL_ARGUMENT_EVENTS,
            "argument",
        )
        _tool_content_failures(
            failures,
            summary,
            tool_output_contains,
            "tool.result",
            _TOOL_OUTPUT_EVENTS,
            "output",
        )
        if (
            max_duration_ms is not None
            and summary.top_level_duration_ms > max_duration_ms
        ):
            failures.append(
                EvaluationFailure(
                    summary.trace_id,
                    f"Top-level trace duration {summary.top_level_duration_ms:.1f} ms exceeds {max_duration_ms:.1f} ms.",
                )
            )
        if require_ok:
            for span in summary.error_spans:
                failures.append(
                    EvaluationFailure(summary.trace_id, f"Failed {_span_label(span)}.")
                )
            for span in summary.open_spans:
                failures.append(
                    EvaluationFailure(
                        summary.trace_id, f"Unclosed {_span_label(span)}."
                    )
                )
    return failures


def _tool_content_failures(
    failures: list[EvaluationFailure],
    summary: TraceSummary,
    specs: Iterable[str],
    attribute: str,
    event_names: frozenset[str],
    label: str,
) -> None:
    for spec in specs:
        tool, text = _tool_text(spec)
        found = any(
            event.name in event_names
            and _tool_name(event.attributes) == tool
            and text
            in json.dumps(
                event.attributes.get(attribute),
                default=str,
                ensure_ascii=False,
                sort_keys=True,
            )
            for event in summary.events
        )
        if not found:
            failures.append(
                EvaluationFailure(
                    summary.trace_id, f"Tool {tool} has no {label} containing {text!r}."
                )
            )


def _tool_text(spec: str) -> tuple[str, str]:
    name, sep, text = spec.partition("=")
    if not sep or not name or not text:
        raise ValueError(f"Expected TOOL=TEXT, got {spec!r}.")
    return name, text


def _tool_count(spec: str) -> tuple[str, int]:
    name, text = _tool_text(spec)
    try:
        count = int(text)
    except ValueError as exc:
        raise ValueError(f"Expected TOOL=COUNT, got {spec!r}.") from exc
    if count < 0:
        raise ValueError(f"Tool call count cannot be negative: {spec!r}.")
    return name, count


def _attributes(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("attributes")
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _tool_name(attributes: Mapping[str, Any]) -> str | None:
    return _text(attributes.get("tool.name"))


def _span_label(span: SpanSummary) -> str:
    tool = _tool_name(span.attributes)
    return f"span {span.name} ({span.span_id})" + (f" for tool {tool}" if tool else "")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AUTOMA-AI JSONL telemetry.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("summary", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("path", type=Path)
        command.add_argument("--json", action="store_true")
        if name == "evaluate":
            for option in (
                "require-event",
                "forbid-event",
                "require-span",
                "require-tool",
                "tool-call-count",
                "tool-argument-contains",
                "tool-output-contains",
            ):
                command.add_argument(f"--{option}", action="append", default=[])
            command.add_argument("--max-duration-ms", type=float)
            command.add_argument("--require-ok", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        records, issues = read_jsonl(args.path)
        summaries = summarize_traces(records)
        failures = (
            evaluate_traces(
                summaries,
                required_events=args.require_event,
                forbidden_events=args.forbid_event,
                required_spans=args.require_span,
                required_tools=args.require_tool,
                tool_call_counts=args.tool_call_count,
                tool_argument_contains=args.tool_argument_contains,
                tool_output_contains=args.tool_output_contains,
                max_duration_ms=args.max_duration_ms,
                require_ok=args.require_ok,
            )
            if args.command == "evaluate"
            else []
        )
    except (OSError, ValueError) as exc:
        print(f"Unable to evaluate {args.path}: {exc}", file=sys.stderr)
        return 2
    for issue in issues:
        print(f"Warning: line {issue.line_number}: {issue.message}", file=sys.stderr)
    if args.command == "summary":
        if args.json:
            print(
                json.dumps(
                    [asdict(summary) for summary in summaries], indent=2, default=str
                )
            )
        else:
            for summary in summaries:
                print(
                    f"trace_id={summary.trace_id} records={summary.record_count} spans={summary.span_count} errors={summary.error_span_count} open={summary.open_span_count} top_level_duration_ms={summary.top_level_duration_ms:.1f} span_names={','.join(summary.span_names) or '-'} events={','.join(summary.event_names) or '-'}"
                )
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "passed": not failures,
                    "trace_count": len(summaries),
                    "failures": [asdict(failure) for failure in failures],
                },
                indent=2,
            )
        )
    elif not failures:
        print(f"PASS: {len(summaries)} trace(s) satisfied the expectations.")
    else:
        for failure in failures:
            print(f"FAIL trace_id={failure.trace_id}: {failure.message}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
