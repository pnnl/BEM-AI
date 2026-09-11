from __future__ import annotations

import json

from automa_ai.telemetry.trace_reader import (
    evaluate_traces,
    main,
    read_jsonl,
    summarize_traces,
)


def _record(record_type: str, **values):
    return {"type": record_type, "trace_id": "trace-1", **values}


def test_reader_skips_invalid_lines_and_summarizes_trace(tmp_path) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(_record("span_start", span_id="agent", name="agent.turn")),
                "not json",
                json.dumps(_record("event", span_id="agent", name="tool.result")),
                json.dumps(
                    _record(
                        "span_end",
                        span_id="agent",
                        name="agent.turn",
                        status="ok",
                        duration_ms=12.5,
                    )
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records, issues = read_jsonl(path)
    summaries = summarize_traces(records)

    assert len(issues) == 1
    assert issues[0].line_number == 2
    assert summaries[0].trace_id == "trace-1"
    assert summaries[0].record_count == 3
    assert summaries[0].span_count == 1
    assert summaries[0].open_span_count == 0
    assert summaries[0].total_duration_ms == 12.5
    assert summaries[0].event_names == ("tool.result",)


def test_evaluate_traces_reports_event_duration_and_health_failures() -> None:
    summaries = summarize_traces(
        [
            _record("span_start", span_id="agent", name="agent.turn"),
            _record("event", span_id="agent", name="tool.request"),
            _record(
                "span_end",
                span_id="agent",
                name="agent.turn",
                status="error",
                duration_ms=25,
            ),
            _record("span_start", span_id="open", name="tool.call"),
        ]
    )

    failures = evaluate_traces(
        summaries,
        required_events=["assistant.final"],
        forbidden_events=["tool.request"],
        max_duration_ms=20,
        require_ok=True,
    )

    assert [failure.message for failure in failures] == [
        "Missing event: assistant.final",
        "Forbidden event: tool.request",
        "Total span duration 25.0 ms exceeds 20.0 ms.",
        "Trace is not clean: 1 error span(s), 1 open span(s).",
    ]


def test_cli_evaluate_returns_nonzero_for_failed_expectation(tmp_path, capsys) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text(
        json.dumps(_record("event", name="assistant.final")) + "\n",
        encoding="utf-8",
    )

    exit_code = main(["evaluate", str(path), "--require-event", "tool.result"])

    assert exit_code == 1
    assert "Missing event: tool.result" in capsys.readouterr().out


def test_cli_summary_json_is_machine_readable(tmp_path, capsys) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text(json.dumps(_record("event", name="assistant.final")) + "\n")

    exit_code = main(["summary", str(path), "--json"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)[0]["trace_id"] == "trace-1"
