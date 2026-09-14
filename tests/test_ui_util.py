from automa_ai.client.ui_util import extract_stream_text


def test_extract_stream_text_reads_status_update_message() -> None:
    update = extract_stream_text(
        {
            "result": {
                "kind": "status-update",
                "status": {"state": "working", "message": {"parts": [{"kind": "text", "text": "Hello"}]}},
            }
        }
    )

    assert update.text == "Hello"
    assert update.is_final is False


def test_extract_stream_text_reads_completed_task_artifact() -> None:
    update = extract_stream_text(
        {
            "result": {
                "kind": "task",
                "status": {"state": "completed"},
                "artifacts": [{"parts": [{"kind": "text", "text": "Final answer"}]}],
            }
        }
    )

    assert update.text == "Final answer"
    assert update.is_final is True


def test_extract_stream_text_marks_final_artifact_update_as_terminal() -> None:
    update = extract_stream_text(
        {
            "result": {
                "kind": "artifact-update",
                "lastChunk": True,
                "artifact": {"parts": [{"kind": "text", "text": "Final answer"}]},
            }
        }
    )

    assert update.text == "Final answer"
    assert update.is_final is True
    assert update.replaces_text is True


def test_extract_stream_text_appends_terminal_artifact_suffix() -> None:
    update = extract_stream_text(
        {
            "result": {
                "kind": "artifact-update",
                "append": True,
                "lastChunk": True,
                "artifact": {"parts": [{"kind": "text", "text": "lo"}]},
            }
        }
    )

    assert update.is_final is True
    assert update.append is True
    assert update.replaces_text is False
