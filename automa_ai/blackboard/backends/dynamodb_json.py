from __future__ import annotations

from typing import Any, Literal

from automa_ai.blackboard.errors import BackendNotConfiguredError, DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.models import BlackboardBackend, BlackboardDocument
from automa_ai.blackboard.schema import BlackboardSchemaRegistry
from automa_ai.blackboard.store import BlackboardStore, bump_revision, BlackboardStoreConfig

class DynamoDBJSONBlackboardStoreConfig(BlackboardStoreConfig):
    backend: Literal[BlackboardBackend.DYNAMODB_JSON] = BlackboardBackend.DYNAMODB_JSON
    dynamodb_table_name: str
    dynamodb_endpoint_url: str | None = None

class DynamoDBJSONBlackboardStore(BlackboardStore):
    """Blackboard store that stores blackboards in AWS DynamoDB.

    This class expects that a DynamoDB table exists with name `config.dynamodb_table_name`
    """
    _config_class: DynamoDBJSONBlackboardStoreConfig

    def __init__(self, config: DynamoDBJSONBlackboardStoreConfig, dynamodb_table=None):
        super().__init__(config=config)

        if dynamodb_table is not None:
            self.table = dynamodb_table
        else:
            if not config.dynamodb_table_name:
                raise BackendNotConfiguredError("dynamodb_table_name is required for dynamodb_json backend.")
            
            self.table = self._load_dynamodb_blackboard_table(
                table_name=config.dynamodb_table_name,
                endpoint_url=config.dynamodb_endpoint_url,
            )

    def load(self, session_id: str) -> BlackboardDocument:
        result = self.table.get_item(Key={"session_id": session_id}, ConsistentRead=True)
        item = result.get("Item")
        if not item:
            raise DocumentNotFoundError(f"Session '{session_id}' has no blackboard document.")
        return BlackboardDocument.from_json_dict(item["document"])

    def create(self, session_id: str, schema_name: str, schema_version: str, initial_data: dict[str, Any] | None = None) -> BlackboardDocument:
        doc = BlackboardDocument(
            session_id=session_id,
            schema_name=schema_name,
            schema_version=schema_version,
            data=initial_data or {},
        )
        self.validator.validate(schema_name, schema_version, doc.data)
        return self.save(doc, expected_revision=None)

    def save(self, doc: BlackboardDocument, expected_revision: int | None = None) -> BlackboardDocument:
        current_revision = -1
        try:
            current = self.load(doc.session_id)
            current_revision = current.revision
        except DocumentNotFoundError:
            # Document does not exist yet; leave current_revision as -1 to indicate absence.
            pass

        if expected_revision is not None and current_revision != expected_revision:
            raise RevisionConflictError(
                f"Expected revision {expected_revision}, found {current_revision}."
            )
        if expected_revision is None and current_revision >= 0:
            doc.revision = current_revision
        bump_revision(doc)

        kwargs = {
            "Item": {"session_id": doc.session_id, "revision": doc.revision, "document": doc.to_json_dict()},
        }

        if current_revision < 0:
            kwargs["ConditionExpression"] = "attribute_not_exists(session_id)"
        else:
            kwargs["ConditionExpression"] = "#rev = :expected"
            kwargs["ExpressionAttributeValues"] = {":expected": current_revision}
            kwargs["ExpressionAttributeNames"] = {"#rev": "revision"}

        try:
            self.table.put_item(**kwargs)
        except Exception as exc:
            raise RevisionConflictError("Conditional write failed due to revision mismatch.") from exc
        return doc

    def _load_dynamodb_blackboard_table(self, table_name: str, endpoint_url: str = None):
        try:
            import boto3
        except ImportError as exc:
            raise BackendNotConfiguredError("boto3 is required for DynamoDB backend.") from exc

        dynamodb = boto3.resource(
            "dynamodb",
            endpoint_url=endpoint_url,
        )

        table = dynamodb.Table(table_name)
        table.load() # This will raise an exception if the table does not exist

        return table