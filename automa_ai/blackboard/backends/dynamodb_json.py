from __future__ import annotations

from typing import Any

from automa_ai.blackboard.errors import BackendNotConfiguredError, DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.models import BlackboardDocument
from automa_ai.blackboard.store import BlackboardStore, bump_revision


class DynamoDBJSONBlackboardStore(BlackboardStore):
    def __init__(self, table_name: str, validator, dynamodb_table=None):
        super().__init__(validator)
        if dynamodb_table is not None:
            self.table = dynamodb_table
        else:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover
                raise BackendNotConfiguredError("boto3 is required for DynamoDB backend.") from exc
            self.table = boto3.resource("dynamodb").Table(table_name)

    def load(self, session_id: str) -> BlackboardDocument:
        result = self.table.get_item(Key={"session_id": session_id})
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
