from __future__ import annotations

import warnings
from typing import Any

from pydantic import BaseModel, Field, model_validator

from automa_ai.blackboard.store import BlackboardStore, BlackboardStoreConfig

class BlackboardConfig(BaseModel):
    model_config = {
        "arbitrary_types_allowed": True,
        "extra": "allow",
    }

    enabled: bool = False
    store: BlackboardStoreConfig | dict | None = None
    schema_name: str
    schema_version: str
    schema: dict[str, Any] | None = None
    schema_description: str | None = None
    initial_data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlackboardConfig":
        return cls.model_validate(data)
    
    @model_validator(mode="before")
    def migrate_old_format(cls, data):
        if "backend" in data and "store" not in data:
            warnings.warn(
                "Passing backend configuration fields directly to BlackboardConfig is deprecated. "
                "Please use the 'store' field with a BlackboardStoreConfig instead. "
                "Example: BlackboardConfig(store={'backend': 'local_json', 'base_dir': '...'}). "
                "The old format will be removed in a future version.",
                DeprecationWarning,
                stacklevel=2
            )
            data["store"] = {
                "backend": data["backend"],
                "s3_bucket": data.get("s3_bucket"),
                "s3_prefix": data.get("s3_prefix"),
                "base_dir": data.get("base_dir"),
                "dynamodb_table_name": data.get("dynamodb_table_name"),
                "dynamodb_endpoint_url": data.get("dynamodb_endpoint_url")
            }

        return data
