from examples.openstudio_ai.ui import (
    _artifact_contains_json_fence,
    _artifact_contains_python_fence,
    _format_status_text_for_display,
    _parse_stream_chunk,
    _should_defer_artifact_render,
    _should_suppress_status_text,
    _split_python_fenced_blocks,
)


def test_openstudio_ui_parses_status_update_separately() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "status-update",
                "contextId": "ctx-1",
                "status": {
                    "state": "working",
                    "message": {
                        "parts": [
                            {
                                "kind": "text",
                                "text": "Inspecting model geometry.",
                            }
                        ]
                    },
                },
            }
        }
    )

    assert event == {
        "kind": "status-update",
        "context_id": "ctx-1",
        "state": "working",
        "text": "Inspecting model geometry.",
        "data": [],
    }


def test_openstudio_ui_parses_artifact_update_separately() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {
                            "kind": "text",
                            "text": "Final model edit summary.",
                        }
                    ]
                },
            }
        }
    )

    assert event == {
        "kind": "artifact-update",
        "context_id": "ctx-1",
        "state": None,
        "text": "Final model edit summary.",
        "data": [],
    }


def test_openstudio_ui_parses_data_artifact_update() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {
                            "kind": "data",
                            "data": {"ok": True, "counts": {"spaces": 6}},
                        }
                    ]
                },
            }
        }
    )

    assert event["kind"] == "artifact-update"
    assert event["context_id"] == "ctx-1"
    assert event["text"] is None
    assert event["data"] == [{"ok": True, "counts": {"spaces": 6}}]


def test_openstudio_ui_parses_mixed_text_and_data_artifact_update() -> None:
    event = _parse_stream_chunk(
        {
            "result": {
                "kind": "artifact-update",
                "contextId": "ctx-1",
                "artifact": {
                    "parts": [
                        {"kind": "text", "text": "Final summary."},
                        {"kind": "data", "data": {"ok": True}},
                    ]
                },
            }
        }
    )

    assert event["text"] == "Final summary."
    assert event["data"] == [{"ok": True}]


def test_openstudio_ui_suppresses_successful_load_skill_status() -> None:
    assert _should_suppress_status_text(
        "\n\n **Tool load_skill responded**: SKILL: sdk_geometry\n\n"
    )


def test_openstudio_ui_suppresses_load_skill_status_by_prefix() -> None:
    assert _should_suppress_status_text("Tool load_skill responded: ")


def test_openstudio_ui_suppresses_openstudio_skill_response() -> None:
    assert _should_suppress_status_text(
        "Tool load_skill responded: SKILL: openstudio_sdk_model_editor\n"
        "SOURCE: /Users/xuwe123/github/BEM-AI/examples/openstudio_ai/"
        "skills/openstudio_sdk_model_editor.md\n\nScope\n\nUse this skill only..."
    )


def test_openstudio_ui_keeps_load_skill_error_status() -> None:
    assert not _should_suppress_status_text(
        "\n\n **Tool load_skill responded**: Error: missing skill\n\n"
    )


def test_openstudio_ui_normalizes_streamed_status_whitespace() -> None:
    assert (
        _format_status_text_for_display(" For example:\n   - **Building")
        == "For example:\n- **Building"
    )


def test_openstudio_ui_limits_excess_status_blank_lines() -> None:
    assert (
        _format_status_text_for_display("First\n\n\n\n   Second")
        == "First\nSecond"
    )


def test_openstudio_ui_removes_blank_lines_before_status_options() -> None:
    assert (
        _format_status_text_for_display(
            "What aspects are you most interested in? For example:\n\n\n\n"
            "Geometry & envelope: number of stories"
        )
        == "What aspects are you most interested in? For example:\n"
        "Geometry & envelope: number of stories"
    )


def test_openstudio_ui_defers_incomplete_markdown_table_rows() -> None:
    assert _should_defer_artifact_render("📐 Geometry\n|")
    assert _should_defer_artifact_render("📐 Geometry\n| Item | Count")
    assert not _should_defer_artifact_render("📐 Geometry\n| Item | Count |\n")
    assert not _should_defer_artifact_render("Plain text without a table")


def test_openstudio_ui_detects_python_script_artifacts() -> None:
    assert _artifact_contains_python_fence("Run this:\n```python\nprint('x')\n```")
    assert _artifact_contains_python_fence("Run this:\n```PYTHON\nprint('x')\n```")
    assert not _artifact_contains_python_fence("```json\n{\"ok\": true}\n```")


def test_openstudio_ui_splits_python_script_from_surrounding_text() -> None:
    assert _split_python_fenced_blocks(
        "Intro\n```python\nprint('x')\n```\nOutro"
    ) == [
        ("text", "Intro\n"),
        ("python", "```python\nprint('x')\n```"),
        ("text", "\nOutro"),
    ]


def test_openstudio_ui_detects_json_data_artifacts() -> None:
    assert _artifact_contains_json_fence("```json\n{\"ok\": true}\n```")
    assert _artifact_contains_json_fence("```JSON\n{\"ok\": true}\n```")
    assert not _artifact_contains_json_fence("```python\nprint('x')\n```")
