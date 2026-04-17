from io import BytesIO

import pytest

from automa_ai.blackboard.backends.dynamodb_json import DynamoDBJSONBlackboardStore
from automa_ai.blackboard.backends.s3_json import S3JSONBlackboardStore
from automa_ai.blackboard.errors import RevisionConflictError
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.config.blackboard import BlackboardConfig


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.etags = {}
        self.version = 0

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {"Body": BytesIO(self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {"ETag": self.etags[(Bucket, Key)]}

    def put_object(self, Bucket, Key, Body, ContentType, IfMatch=None, IfNoneMatch=None):
        existing = (Bucket, Key) in self.objects
        if IfNoneMatch == "*" and existing:
            raise RuntimeError("exists")
        if IfMatch is not None:
            if not existing or self.etags[(Bucket, Key)] != IfMatch:
                raise RuntimeError("conflict")
        self.version += 1
        self.objects[(Bucket, Key)] = Body
        self.etags[(Bucket, Key)] = f'"etag-{self.version}"'


class FakeDynamoTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, ConsistentRead):
        item = self.items.get(Key["session_id"])
        return {"Item": item} if item else {}

    def put_item(
        self,
        Item,
        ConditionExpression,
        ExpressionAttributeValues=None,
        ExpressionAttributeNames=None,
    ):
        sid = Item["session_id"]
        current = self.items.get(sid)
        if (
            ConditionExpression == "attribute_not_exists(session_id)"
            and current is not None
        ):
            raise RuntimeError("exists")
        if ConditionExpression == "#rev = :expected":
            expected = ExpressionAttributeValues[":expected"]
            if current is None or current.get("revision") != expected:
                raise RuntimeError("conflict")
        self.items[sid] = Item

@pytest.fixture
def s3_blackboard():
    fake_s3 = FakeS3()

    config = BlackboardConfig(
        enabled=True,
        backend="s3_json",
        schema_name="test",
        schema_version="1",
        schema={"type": "object", "properties": {"items": {"type": "array"}}},
        s3_bucket="bucket",
        s3_prefix="prefix",
    )

    return S3JSONBlackboardStore(config=config, s3_client=fake_s3)

@pytest.fixture
def dynamodb_blackboard():
    fake_dynamodb_table = FakeDynamoTable()

    config = BlackboardConfig(
        enabled=True,
        backend="dynamodb_json",
        schema_name="test",
        schema_version="1",
        schema={"type": "object", "properties": {"items": {"type": "array"}}},
        dynamodb_table_name="table",
    )

    return DynamoDBJSONBlackboardStore(config=config, dynamodb_table=fake_dynamodb_table)

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


def test_s3_backend_mocked_roundtrip(s3_blackboard):
    doc = s3_blackboard.create("s1", "test", "1", {"items": []})
    assert doc.revision == 1
    loaded = s3_blackboard.load("s1")
    assert loaded.data["items"] == []


def test_s3_backend_uses_conditional_write_on_existing_document(s3_blackboard):
    created = s3_blackboard.create("s1", "test", "1", {"items": []})

    stale = created.model_copy(deep=True)
    stale.data["items"].append("stale")
    s3_blackboard.save(stale)

    with pytest.raises(RevisionConflictError):
        s3_blackboard.save(created)


def test_dynamodb_backend_conditional_conflict(dynamodb_blackboard):
    created = dynamodb_blackboard.create("s1", "test", "1", {"items": []})
    assert created.revision == 1

    with pytest.raises(RevisionConflictError):
        dynamodb_blackboard.save(created, expected_revision=2)


def test_dynamodb_backend_save_without_expected_revision_updates_existing_document(dynamodb_blackboard):
    created = dynamodb_blackboard.create("s1", "test", "1", {"items": []})

    created.data["items"].append("item")
    updated = dynamodb_blackboard.save(created)

    assert updated.revision == 2
    loaded = dynamodb_blackboard.load("s1")
    assert loaded.data["items"] == ["item"]


def test_dynamodb_backend_create_and_update_with_expected_revision(dynamodb_blackboard):
    created = dynamodb_blackboard.create("s2", "test", "1", {"items": []})

    created.data["items"].append("ok")
    assert created.revision == 1

    updated = dynamodb_blackboard.save(created, expected_revision=1)
    assert updated.revision == 2

    loaded = dynamodb_blackboard.load("s2")
    assert loaded.data["items"] == ["ok"]