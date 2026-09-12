from __future__ import annotations

import json

from automa_ai.telemetry.trace_reader import evaluate_traces, main, summarize_traces


def _record(kind: str, **values):
    return {"type": kind, "trace_id": "trace-1", **values}


def _tool_trace() -> list[dict]:
    return [
        _record("span_start", span_id="agent", name="agent.turn"),
        _record(
            "span_start",
            span_id="tool",
            parent_span_id="agent",
            name="tool.call",
            attributes={"tool.name": "run_python", "tool.arguments": {"code": "x=1"}},
        ),
        _record(
            "event",
            span_id="tool",
            name="tool.input",
            attributes={"tool.name": "run_python", "tool.arguments": {"code": "x=1"}},
        ),
        _record(
            "event",
            span_id="tool",
            name="tool.output",
            attributes={"tool.name": "run_python", "tool.result": "answer: 1"},
        ),
        _record("span_end", span_id="tool", status="ok", duration_ms=40),
        _record("span_end", span_id="agent", status="ok", duration_ms=100),
    ]


def test_evaluator_retains_tool_attributes_and_counts() -> None:
    summary = summarize_traces(_tool_trace())
    assert summary[0].spans[1].attributes["tool.name"] == "run_python"
    assert summary[0].events[1].attributes["tool.result"] == "answer: 1"
    assert (
        evaluate_traces(
            summary,
            required_spans=["tool.call"],
            required_tools=["run_python"],
            tool_call_counts=["run_python=1"],
            tool_argument_contains=["run_python=x=1"],
            tool_output_contains=["run_python=answer: 1"],
            require_ok=True,
        )
        == []
    )


def test_duration_uses_root_span_not_nested_span_sum() -> None:
    summary = summarize_traces(_tool_trace())[0]
    assert summary.top_level_duration_ms == 100
    assert evaluate_traces([summary], max_duration_ms=110) == []
    assert "Top-level trace duration 100.0 ms exceeds 99.0 ms." in [
        failure.message for failure in evaluate_traces([summary], max_duration_ms=99)
    ]


def test_require_ok_identifies_failed_tool_span() -> None:
    records = _tool_trace()
    records[4]["status"] = "error"
    failures = evaluate_traces(summarize_traces(records), require_ok=True)
    assert [failure.message for failure in failures] == [
        "Failed span tool.call (tool) for tool run_python."
    ]


def test_cli_reports_failed_tool_count(tmp_path, capsys) -> None:
    path = tmp_path / "telemetry.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in _tool_trace()) + "\n")
    assert main(["evaluate", str(path), "--tool-call-count", "run_python=2"]) == 1
    assert "Tool run_python call count is 1; expected 2." in capsys.readouterr().out
