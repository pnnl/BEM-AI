"""Read, summarize, and evaluate AUTOMA-AI JSONL telemetry traces.

The reader deliberately operates on the recorder's public JSONL shape rather
than runtime objects.  It is therefore safe to use after a process exits and
does not need model, tool, or telemetry-recorder dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_MISSING_TRACE_ID = "<missing-trace-id>"


@dataclass(frozen=True)
class ReadIssue:
    """A malformed JSONL line that was skipped while reading a log."""

    line_number: int
    message: str


@dataclass(frozen=True)
class TraceSummary:
    """A compact, backend-independent view of one telemetry trace."""

    trace_id: str
    record_count: int
    span_count: int
    open_span_count: int
    error_span_count: int
    total_duration_ms: float
    event_names: tuple[str, ...]


@dataclass(frozen=True)
class EvaluationFailure:
    """One expectation that a trace did not satisfy."""

    trace_id: str
    message: str


def read_jsonl(path: str | Path) -> tuple[list[dict[str, Any]], list[ReadIssue]]:
    """Read valid JSON object records from a telemetry JSONL file.

    Malformed lines are reported rather than aborting inspection of a partially
    written log.  A missing file remains an error because it usually indicates
    an incorrect telemetry path.
    """
    records: list[dict[str, Any]] = []
    issues: list[ReadIssue] = []
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                issues.append(ReadIssue(line_number, f"Invalid JSON: {exc.msg}"))
                continue
            if not isinstance(item, dict):
                issues.append(ReadIssue(line_number, "Expected a JSON object."))
                continue
            records.append(item)
    return records, issues


def summarize_traces(records: Iterable[dict[str, Any]]) -> list[TraceSummary]:
    """Group recorder records into deterministic trace summaries."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        trace_id = record.get("trace_id")
        grouped[
            trace_id if isinstance(trace_id, str) and trace_id else _MISSING_TRACE_ID
        ].append(record)

    summaries: list[TraceSummary] = []
    for trace_id in sorted(grouped):
        trace_records = grouped[trace_id]
        started_spans = {
            record.get("span_id")
            for record in trace_records
            if record.get("type") == "span_start" and record.get("span_id")
        }
        ended_spans = {
            record.get("span_id")
            for record in trace_records
            if record.get("type") == "span_end" and record.get("span_id")
        }
        error_span_count = sum(
            1
            for record in trace_records
            if record.get("type") == "span_end" and record.get("status") == "error"
        )
        total_duration_ms = sum(
            duration
            for record in trace_records
            if record.get("type") == "span_end"
            for duration in (_as_nonnegative_float(record.get("duration_ms")),)
            if duration is not None
        )
        event_names = tuple(
            sorted(
                {
                    name
                    for record in trace_records
                    if record.get("type") == "event"
                    for name in (record.get("name"),)
                    if isinstance(name, str) and name
                }
            )
        )
        summaries.append(
            TraceSummary(
                trace_id=trace_id,
                record_count=len(trace_records),
                span_count=len(started_spans),
                open_span_count=len(started_spans - ended_spans),
                error_span_count=error_span_count,
                total_duration_ms=total_duration_ms,
                event_names=event_names,
            )
        )
    return summaries


def evaluate_traces(
    summaries: Sequence[TraceSummary],
    *,
    required_events: Iterable[str] = (),
    forbidden_events: Iterable[str] = (),
    max_duration_ms: float | None = None,
    require_ok: bool = False,
) -> list[EvaluationFailure]:
    """Return expectation failures for every trace in a log.

    Event expectations are intentionally generic: callers can assert stable
    framework events such as ``tool.result`` or application-owned events
    without the CLI needing application-specific knowledge.
    """
    if not summaries:
        return [EvaluationFailure(_MISSING_TRACE_ID, "No trace records found.")]

    required = set(required_events)
    forbidden = set(forbidden_events)
    failures: list[EvaluationFailure] = []
    for summary in summaries:
        event_names = set(summary.event_names)
        for name in sorted(required - event_names):
            failures.append(
                EvaluationFailure(summary.trace_id, f"Missing event: {name}")
            )
        for name in sorted(forbidden & event_names):
            failures.append(
                EvaluationFailure(summary.trace_id, f"Forbidden event: {name}")
            )
        if max_duration_ms is not None and summary.total_duration_ms > max_duration_ms:
            failures.append(
                EvaluationFailure(
                    summary.trace_id,
                    "Total span duration "
                    f"{summary.total_duration_ms:.1f} ms exceeds {max_duration_ms:.1f} ms.",
                )
            )
        if require_ok and (summary.error_span_count or summary.open_span_count):
            failures.append(
                EvaluationFailure(
                    summary.trace_id,
                    "Trace is not clean: "
                    f"{summary.error_span_count} error span(s), "
                    f"{summary.open_span_count} open span(s).",
                )
            )
    return failures


def _as_nonnegative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect AUTOMA-AI JSONL telemetry.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("summary", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("path", type=Path, help="Path to a telemetry JSONL file.")
        command.add_argument(
            "--json", action="store_true", help="Emit machine-readable JSON."
        )
        if name == "evaluate":
            command.add_argument("--require-event", action="append", default=[])
            command.add_argument("--forbid-event", action="append", default=[])
            command.add_argument("--max-duration-ms", type=float)
            command.add_argument("--require-ok", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the telemetry reader CLI and return a shell-compatible exit code."""
    args = _build_parser().parse_args(argv)
    try:
        records, issues = read_jsonl(args.path)
    except OSError as exc:
        print(f"Unable to read {args.path}: {exc}", file=sys.stderr)
        return 2
    summaries = summarize_traces(records)
    for issue in issues:
        print(f"Warning: line {issue.line_number}: {issue.message}", file=sys.stderr)

    if args.command == "summary":
        _print_summaries(summaries, as_json=args.json)
        return 0

    failures = evaluate_traces(
        summaries,
        required_events=args.require_event,
        forbidden_events=args.forbid_event,
        max_duration_ms=args.max_duration_ms,
        require_ok=args.require_ok,
    )
    _print_evaluation(summaries, failures, as_json=args.json)
    return 1 if failures else 0


def _print_summaries(summaries: Sequence[TraceSummary], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(summary) for summary in summaries], indent=2))
        return
    for summary in summaries:
        events = ",".join(summary.event_names) or "-"
        print(
            f"trace_id={summary.trace_id} records={summary.record_count} "
            f"spans={summary.span_count} errors={summary.error_span_count} "
            f"open={summary.open_span_count} duration_ms={summary.total_duration_ms:.1f} "
            f"events={events}"
        )


def _print_evaluation(
    summaries: Sequence[TraceSummary],
    failures: Sequence[EvaluationFailure],
    *,
    as_json: bool,
) -> None:
    if as_json:
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
        return
    if not failures:
        print(f"PASS: {len(summaries)} trace(s) satisfied the expectations.")
        return
    for failure in failures:
        print(f"FAIL trace_id={failure.trace_id}: {failure.message}")


if __name__ == "__main__":
    raise SystemExit(main())
