from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BlackboardBackend(str, Enum):
    LOCAL_JSON = "local_json"
    S3_JSON = "s3_json"
    DYNAMODB_JSON = "dynamodb_json"


class ApprovalStatus(str, Enum):
    """Durable states for a human decision checkpoint."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESUMED = "resumed"
    CANCELLED = "cancelled"


class ApprovalRecord(BaseModel):
    """A reviewable reference to a blackboard artifact at one revision."""

    approval_id: str = Field(default_factory=lambda: uuid4().hex)
    status: ApprovalStatus = ApprovalStatus.PENDING
    artifact_path: str
    artifact_revision: int
    title: str | None = None
    requested_at: datetime = Field(default_factory=utc_now)
    requested_by: str | None = None
    request_note: str | None = None
    expires_at: datetime | None = None
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    resumed_by: str | None = None
    resumed_at: datetime | None = None


class BlackboardEvent(BaseModel):
    ts: datetime = Field(default_factory=utc_now)
    actor: str | None = None
    op: str
    path: str | None = None
    before: Any = None
    after: Any = None
    note: str | None = None


class BlackboardOp(BaseModel):
    op: Literal["set", "merge", "append", "remove"]
    path: str
    value: Any = None


class BlackboardPatch(BaseModel):
    ops: list[BlackboardOp]
    actor: str | None = None
    note: str | None = None


class BlackboardDocument(BaseModel):
    session_id: str
    schema_name: str
    schema_version: str
    revision: int = 0
    updated_at: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    events: list[BlackboardEvent] = Field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "BlackboardDocument":
        return cls.model_validate(payload)
