from __future__ import annotations

import json
from typing import Any

from automa_ai.blackboard.errors import BackendNotConfiguredError, DocumentNotFoundError, RevisionConflictError
from automa_ai.blackboard.models import BlackboardDocument
from automa_ai.blackboard.store import BlackboardStore, bump_revision


class S3JSONBlackboardStore(BlackboardStore):
    def __init__(self, bucket: str, prefix: str, validator, s3_client=None):
        super().__init__(validator)
        self.bucket = bucket
        self.prefix = prefix.rstrip("/")
        if s3_client is not None:
            self.s3 = s3_client
        else:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover
                raise BackendNotConfiguredError("boto3 is required for S3 backend.") from exc
            self.s3 = boto3.client("s3")

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}/{session_id}.blackboard.json"

    def load(self, session_id: str) -> BlackboardDocument:
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=self._key(session_id))
        except Exception as exc:
            raise DocumentNotFoundError(f"Session '{session_id}' has no blackboard document.") from exc
        payload = json.loads(obj["Body"].read().decode("utf-8"))
        return BlackboardDocument.from_json_dict(payload)

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
        key = self._key(doc.session_id)
        current_revision = -1
        current_etag = None
        try:
            head = self.s3.head_object(Bucket=self.bucket, Key=key)
            current_etag = head.get("ETag")
        except Exception:
            # head_object may raise a provider-specific not-found error for missing keys.
            pass
        else:
            current = self.load(doc.session_id)
            current_revision = current.revision

        if expected_revision is not None and expected_revision != current_revision:
            raise RevisionConflictError(
                f"Expected revision {expected_revision}, found {current_revision}."
            )
        if expected_revision is None and current_revision >= 0:
            doc.revision = current_revision
        bump_revision(doc)

        put_kwargs = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": json.dumps(doc.to_json_dict()).encode("utf-8"),
            "ContentType": "application/json",
        }
        if current_etag is not None:
            put_kwargs["IfMatch"] = current_etag
        else:
            put_kwargs["IfNoneMatch"] = "*"

        try:
            self.s3.put_object(**put_kwargs)
        except Exception as exc:
            raise RevisionConflictError("Conditional write failed due to revision mismatch.") from exc
        return doc
