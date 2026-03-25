from __future__ import annotations

from automa_ai.learning.workflow import build_review_payload


def test_build_review_payload_compact_fields_present():
    payload = build_review_payload(
        query="hello",
        final_response={"status": "completed", "errors": ["none"]},
        response_type="data",
        session_id="sid",
        task_id="tid",
        blackboard_store=None,
    )

    assert payload["query"] == "hello"
    assert payload["task_status"] == "completed"
    assert payload["key_execution_summary"]["session_id"] == "sid"
    assert payload["errors"] == ["none"]


class _DummyMessage:
    def __init__(self, content):
        self.content = content


def test_build_review_payload_normalizes_langgraph_message_dict():
    payload = build_review_payload(
        query="hello",
        final_response={"messages": [{"content": "first"}, _DummyMessage("second")]},
        response_type="text",
        session_id="sid",
        task_id="tid",
    )

    assert payload["final_response"]["kind"] == "langgraph_messages"
    assert payload["final_response"]["message_count"] == 2
    assert payload["final_response"]["last_message"] == "second"
