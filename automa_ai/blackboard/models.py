from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    events: list[BlackboardEvent] = Field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_json_dict(cls, payload: dict[str, Any]) -> "BlackboardDocument":
        return cls.model_validate(payload)
