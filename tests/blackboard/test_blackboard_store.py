from pathlib import Path
from typing import Any, Literal

import pytest

from automa_ai.blackboard.backends.local_json import LocalJSONBlackboardStore, LocalJSONBlackboardStoreConfig
from automa_ai.blackboard.errors import RevisionConflictError, SchemaValidationError, DocumentNotFoundError
from automa_ai.blackboard.models import BlackboardPatch, BlackboardDocument
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.blackboard.store import (
    get_path_value,
    parse_path,
    BlackboardStoreConfig,
    BlackboardStore,
    BlackboardStoreRegistry,
    create_blackboard_store,
    bump_revision,
)
from automa_ai.config.blackboard import BlackboardConfig


@pytest.fixture
def store(tmp_path: Path):

    config = LocalJSONBlackboardStoreConfig(
        backend="local_json",
        base_dir=str(tmp_path.parent),
    )

    return LocalJSONBlackboardStore(config=config)

@pytest.fixture(scope="session", autouse=True)
def register_blackboard_schema():
    BlackboardSchemaRegistry.register(
        name="ce_workflow",
        version="1.0",
        json_schema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "object",
                            "properties": {"confirmed_text": {"type": "string"}},
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


def test_custom_blackboard_store_registry():
    """Test that a custom blackboard store can be registered and used."""

    # Define a custom in-memory store
    class InMemoryBlackboardStoreConfig(BlackboardStoreConfig):
        backend: Literal["in_memory"] = "in_memory"

    class InMemoryBlackboardStore(BlackboardStore):
        _config_class = InMemoryBlackboardStoreConfig

        def __init__(self, config: InMemoryBlackboardStoreConfig):
            super().__init__(config)
            self._storage: dict[str, BlackboardDocument] = {}

        def load(self, session_id: str) -> BlackboardDocument:
            if session_id not in self._storage:
                raise DocumentNotFoundError(f"Session '{session_id}' not found")
            return self._storage[session_id]

        def create(
            self,
            session_id: str,
            schema_name: str,
            schema_version: str,
            initial_data: dict[str, Any] | None = None,
        ) -> BlackboardDocument:
            doc = BlackboardDocument(
                session_id=session_id,
                schema_name=schema_name,
                schema_version=schema_version,
                data=initial_data or {},
            )
            self.validator.validate(schema_name, schema_version, doc.data)
            return self.save(doc, expected_revision=None)

        def save(self, doc: BlackboardDocument, expected_revision: int | None = None) -> BlackboardDocument:
            if doc.session_id in self._storage:
                existing = self._storage[doc.session_id]
                if expected_revision is not None and existing.revision != expected_revision:
                    raise RevisionConflictError(
                        f"Expected revision {expected_revision}, found {existing.revision}"
                    )
                if expected_revision is None:
                    doc.revision = existing.revision

            bump_revision(doc)
            self._storage[doc.session_id] = doc
            return doc

    BlackboardStoreRegistry.register("in_memory", InMemoryBlackboardStore)
    
    store = create_blackboard_store({"backend": "in_memory"})

    assert isinstance(store, InMemoryBlackboardStore)

    # Test create
    doc = store.create(
        session_id="custom-test",
        schema_name="ce_workflow",
        schema_version="1.0",
        initial_data={
            "project": {"description": {"confirmed_text": "Custom store test"}},
            "recommended_ces": [],
        },
    )

    assert doc.revision == 1
    assert doc.data["project"]["description"]["confirmed_text"] == "Custom store test"

    # Test patch
    updated = store.apply_patch(
        "custom-test",
        BlackboardPatch(
            ops=[
                {"op": "append", "path": "recommended_ces", "value": "CUSTOM-01"},
                {"op": "set", "path": "location", "value": "Custom Location"},
            ],
            actor="test",
        ),
        expected_revision=1,
    )

    assert updated.revision == 2
    assert updated.data["recommended_ces"] == ["CUSTOM-01"]
    assert updated.data["location"] == "Custom Location"

    # Test load
    loaded = store.load("custom-test")
    assert loaded.revision == 2
    assert loaded.data["location"] == "Custom Location"


def test_backward_compatibility_with_blackboard_config(tmp_path: Path):
    """Test that BlackboardStore can be instantiated with old-style BlackboardConfig."""
    # Create BlackboardConfig using old-style format (backend fields directly on config)
    config = BlackboardConfig(
        enabled=True,
        backend="local_json",
        base_dir=str(tmp_path),
        schema_name="permitce_workflow",
        schema_version="1.0.0",
        schema_description=(
            "Shared CE workflow state across drafter, CE expert, EC expert, and report expert."
        ),
        schema={
            "type": "object",
            "properties": {
                "project": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "object",
                            "properties": {"confirmed_text": {"type": "string"}},
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
        initial_data={
            "project": {},
            "recommended_ces": []
        },
    )

    # The migrate_old_format validator should have created config.store
    assert config.store is not None
    print(type(config.store))
    assert isinstance(config.store, BlackboardStoreConfig)
    assert config.store.backend == "local_json"
    assert config.store.base_dir == str(tmp_path)

    # Instantiate store directly using BlackboardConfig (backward compatibility)
    store = LocalJSONBlackboardStore(config)

    # Verify store was created correctly
    assert isinstance(store, LocalJSONBlackboardStore)
