from pathlib import Path
import uuid
import pytest

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.errors import DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.blackboard.store import BlackboardStoreConfig
from automa_ai.blackboard.tools import build_blackboard_tools
from automa_ai.agents.remote_agent import (
    set_subagent_context_id,
    reset_subagent_context_id,
)

@pytest.fixture
def session_id():
    return f"session-{uuid.uuid4()}"

@pytest.fixture
def store(tmp_path: Path, session_id):
    config = BlackboardStoreConfig(
        backend="local_json",
        base_dir=str(tmp_path.parent),
    )
    store = LocalJSONBlackboardStore(config=config)
    store.create(session_id, "test", "1", {"items": []})
    return store

@pytest.fixture(scope="session", autouse=True)
def register_blackboard_schema():
    BlackboardSchemaRegistry.register(
        name="test",
        version="1",
        json_schema=        {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "string"}},
                "meta": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
                "field": {"type": "string"},
            },
            "required": ["items"],
        },

    )

@pytest.fixture
def tools(store):
    return {t.name: t for t in build_blackboard_tools(store)}

def test_tool_wrapper_append_operation(tools, session_id):
    write_result = tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "append", "path": "items", "value": "a"}],
        expected_revision=1,
        actor="tester",
    )

    assert write_result["revision"] == 2
    read_result = tools["blackboard_read"].func(
        session_id=session_id, path="items"
    )
    assert read_result["data"] == ["a"]


def test_tool_wrapper_set_operation(tools, session_id):
    tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "set", "path": "field", "value": "hello"}],
        expected_revision=1,
    )

    read_result = tools["blackboard_read"].func(
        session_id=session_id, path="field"
    )
    assert read_result["data"] == "hello"


def test_tool_wrapper_merge_operation(tools, session_id):
    tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "set", "path": "meta", "value": {"a": 1}}],
        expected_revision=1,
    )
    tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "merge", "path": "meta", "value": {"b": 2}}],
        expected_revision=2,
    )

    read_result = tools["blackboard_read"].func(session_id=session_id, path="meta")
    assert read_result["data"] == {"a": 1, "b": 2}


def test_tool_wrapper_remove_operation(tools, session_id):
    tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "set", "path": "field", "value": "delete-me"}],
        expected_revision=1,
    )
    tools["blackboard_write"].func(
        session_id=session_id,
        ops=[{"op": "remove", "path": "field"}],
        expected_revision=2,
    )

    read_result = tools["blackboard_read"].func(
        session_id=session_id, path="field"
    )
    assert read_result["data"] is None


def test_tool_wrapper_write_conflict_error(tools, session_id):
    with pytest.raises(RevisionConflictError):
        tools["blackboard_write"].func(
            session_id=session_id,
            ops=[{"op": "append", "path": "items", "value": "a"}],
            expected_revision=99,
        )


def test_tool_wrapper_nonexistent_session_errors(tools):
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


def test_tool_wrapper_read_nonexistent_path_returns_none(tools, session_id):
    read_result = tools["blackboard_read"].func(
        session_id=session_id, path="does.not.exist"
    )
    assert read_result["data"] is None


def test_tool_wrapper_uses_context_session_when_omitted(tools, session_id):
    token = set_subagent_context_id(session_id)
    try:
        tools["blackboard_write"].func(
            ops=[{"op": "append", "path": "items", "value": "ctx"}],
            expected_revision=1,
        )
        read_result = tools["blackboard_read"].func(path="items")
    finally:
        reset_subagent_context_id(token)

    assert read_result["session_id"] == session_id
    assert read_result["data"] == ["ctx"]
