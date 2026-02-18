from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BlackboardConfig(BaseModel):
    enabled: bool = False
    backend: str = "local_json"
    schema_name: str
    schema_version: str
    schema: dict[str, Any]
    schema_description: str | None = None
    initial_data: dict[str, Any] = Field(default_factory=dict)

    base_dir: str | None = None
    s3_bucket: str | None = None
    s3_prefix: str = "blackboards"
    dynamodb_table: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlackboardConfig":
        return cls.model_validate(data)
