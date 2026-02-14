from pathlib import Path

import pytest

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.errors import DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.schema import BlackboardSchemaRegistry, BlackboardSchemaValidator
from automa_ai.blackboard.tools import build_blackboard_tools
from automa_ai.agents.remote_agent import set_subagent_context_id, reset_subagent_context_id


def build_store(tmp_path: Path):
    registry = BlackboardSchemaRegistry()
    registry.register(
        "test",
        "1",
        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "string"}},
                "meta": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
                "field": {"type": "string"},
            },
            "required": ["items"],
        },
    )
    validator = BlackboardSchemaValidator(registry)
    store = LocalJSONBlackboardStore(str(tmp_path), validator)
    store.create("session-tools", "test", "1", {"items": []})
    return store


def _tools(tmp_path: Path):
    return {t.name: t for t in build_blackboard_tools(build_store(tmp_path))}


def test_tool_wrapper_append_operation(tmp_path: Path):
    tools = _tools(tmp_path)
    write_result = tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "append", "path": "items", "value": "a"}],
        expected_revision=1,
        actor="tester",
    )

    assert write_result["revision"] == 2
    read_result = tools["blackboard_read"].func(session_id="session-tools", path="items")
    assert read_result["data"] == ["a"]


def test_tool_wrapper_set_operation(tmp_path: Path):
    tools = _tools(tmp_path)
    tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "set", "path": "field", "value": "hello"}],
        expected_revision=1,
    )

    read_result = tools["blackboard_read"].func(session_id="session-tools", path="field")
    assert read_result["data"] == "hello"


def test_tool_wrapper_merge_operation(tmp_path: Path):
    tools = _tools(tmp_path)
    tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "set", "path": "meta", "value": {"a": 1}}],
        expected_revision=1,
    )
    tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "merge", "path": "meta", "value": {"b": 2}}],
        expected_revision=2,
    )

    read_result = tools["blackboard_read"].func(session_id="session-tools", path="meta")
    assert read_result["data"] == {"a": 1, "b": 2}


def test_tool_wrapper_remove_operation(tmp_path: Path):
    tools = _tools(tmp_path)
    tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "set", "path": "field", "value": "delete-me"}],
        expected_revision=1,
    )
    tools["blackboard_write"].func(
        session_id="session-tools",
        ops=[{"op": "remove", "path": "field"}],
        expected_revision=2,
    )

    read_result = tools["blackboard_read"].func(session_id="session-tools", path="field")
    assert read_result["data"] is None


def test_tool_wrapper_write_conflict_error(tmp_path: Path):
    tools = _tools(tmp_path)
    with pytest.raises(RevisionConflictError):
        tools["blackboard_write"].func(
            session_id="session-tools",
            ops=[{"op": "append", "path": "items", "value": "a"}],
            expected_revision=99,
        )


def test_tool_wrapper_nonexistent_session_errors(tmp_path: Path):
    tools = _tools(tmp_path)
    with pytest.raises(DocumentNotFoundError):
        tools["blackboard_read"].func(session_id="missing", path="items")

    with pytest.raises(DocumentNotFoundError):
        tools["blackboard_get_revision"].func(session_id="missing")

    with pytest.raises(DocumentNotFoundError):
        tools["blackboard_write"].func(
            session_id="missing",
            ops=[{"op": "append", "path": "items", "value": "a"}],
            expected_revision=1,
        )


def test_tool_wrapper_read_nonexistent_path_returns_none(tmp_path: Path):
    tools = _tools(tmp_path)
    read_result = tools["blackboard_read"].func(session_id="session-tools", path="does.not.exist")
    assert read_result["data"] is None


def test_tool_wrapper_uses_context_session_when_omitted(tmp_path: Path):
    tools = _tools(tmp_path)
    token = set_subagent_context_id("session-tools")
    try:
        tools["blackboard_write"].func(
            ops=[{"op": "append", "path": "items", "value": "ctx"}],
            expected_revision=1,
        )
        read_result = tools["blackboard_read"].func(path="items")
    finally:
        reset_subagent_context_id(token)

    assert read_result["session_id"] == "session-tools"
    assert read_result["data"] == ["ctx"]
