from pathlib import Path

import pytest

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore
from automa_ai.blackboard.errors import RevisionConflictError, SchemaValidationError
from automa_ai.blackboard.models import BlackboardPatch
from automa_ai.blackboard.schema import BlackboardSchemaRegistry, BlackboardSchemaValidator
from automa_ai.blackboard.store import get_path_value, parse_path


@pytest.fixture
def schema_registry():
    registry = BlackboardSchemaRegistry()
    registry.register(
        "ce_workflow",
        "1.0",
        {
            "type": "object",
            "properties": {
                "project": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "object",
                            "properties": {
                                "confirmed_text": {"type": "string"}
                            },
                            "required": ["confirmed_text"],
                        }
                    },
                },
                "recommended_ces": {"type": "array", "items": {"type": "string"}},
                "location": {"type": "string"},
                "resources": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project", "recommended_ces"],
        },
    )
    return registry


@pytest.fixture
def store(tmp_path: Path, schema_registry):
    validator = BlackboardSchemaValidator(schema_registry)
    return LocalJSONBlackboardStore(str(tmp_path), validator)


def test_parse_path_and_get_path_value():
    assert parse_path("a.b[0].c") == ["a", "b", 0, "c"]
    data = {"a": {"b": [{"c": 42}]}}
    assert get_path_value(data, "a.b[0].c") == 42


def test_local_backend_rejects_path_traversal_session_id(store):
    with pytest.raises(ValueError):
        store.create(
            session_id="../escape",
            schema_name="ce_workflow",
            schema_version="1.0",
            initial_data={"project": {"description": {"confirmed_text": "draft"}}, "recommended_ces": []},
        )


def test_local_backend_create_save_and_apply_patch(store):
    doc = store.create(
        session_id="s1",
        schema_name="ce_workflow",
        schema_version="1.0",
        initial_data={"project": {"description": {"confirmed_text": "draft"}}, "recommended_ces": []},
    )
    assert doc.revision == 1

    updated = store.apply_patch(
        "s1",
        BlackboardPatch(ops=[{"op": "set", "path": "location", "value": "WA"}], actor="user"),
        expected_revision=1,
    )
    assert updated.revision == 2
    assert updated.data["location"] == "WA"
    assert updated.events[-1].op == "set"


def test_schema_validation_failure(store):
    store.create(
        session_id="s2",
        schema_name="ce_workflow",
        schema_version="1.0",
        initial_data={"project": {"description": {"confirmed_text": "draft"}}, "recommended_ces": []},
    )

    with pytest.raises(SchemaValidationError):
        store.apply_patch(
            "s2",
            BlackboardPatch(ops=[{"op": "set", "path": "project.description.confirmed_text", "value": 123}]),
            expected_revision=1,
        )


def test_optimistic_concurrency_conflict(store):
    store.create(
        session_id="s3",
        schema_name="ce_workflow",
        schema_version="1.0",
        initial_data={"project": {"description": {"confirmed_text": "draft"}}, "recommended_ces": []},
    )

    store.apply_patch(
        "s3",
        BlackboardPatch(ops=[{"op": "set", "path": "location", "value": "CA"}]),
        expected_revision=1,
    )

    with pytest.raises(RevisionConflictError):
        store.apply_patch(
            "s3",
            BlackboardPatch(ops=[{"op": "set", "path": "location", "value": "NY"}]),
            expected_revision=1,
        )


def test_ce_workflow_scenario(store):
    store.create(
        session_id="ce-session",
        schema_name="ce_workflow",
        schema_version="1.0",
        initial_data={"project": {"description": {"confirmed_text": "draft"}}, "recommended_ces": []},
    )
    doc = store.apply_patch(
        "ce-session",
        BlackboardPatch(
            ops=[
                {"op": "set", "path": "project.description.confirmed_text", "value": "Final project summary"},
                {"op": "append", "path": "recommended_ces", "value": "CE-01"},
                {"op": "set", "path": "location", "value": "Seattle, WA"},
                {"op": "set", "path": "resources", "value": ["Wetlands", "Forest"]},
            ],
            actor="drafter",
            note="CE sequence",
        ),
        expected_revision=1,
    )

    assert doc.data["project"]["description"]["confirmed_text"] == "Final project summary"
    assert doc.data["recommended_ces"] == ["CE-01"]
    assert doc.data["resources"] == ["Wetlands", "Forest"]
    assert [event.op for event in doc.events] == ["set", "append", "set", "set"]
